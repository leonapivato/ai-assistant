# 259. An effect is claimed once per goal before it is dispatched, and a turn-start pass reconciles what an earlier turn left uncertain or unfinished

- Status: Proposed
- **Partially supersedes [ADR-0014](0014-planning-model.md), in two scopes** — **§4's transition
  table** and **§5's `PlanStore` member enumeration, `PlanExport` shape and `delete_goal`
  cascade** — and §13 shows the working for both. That table gains one row —
  `INDETERMINATE → SUCCEEDED`, triggered by a reconciliation that established the effect, also
  setting `output` and `finished_at` — because a reader holding only §4, which states that *"every
  legal move is enumerated in §4 and enforced by `PlanExecution`"*, builds a tracker that refuses
  the one move by which an uncertain effect is ever resolved. **Every other move in that table
  binds entire**, and so do §4's terminal `SUCCEEDED`/`SKIPPED` rule, its *"`FAILED` is terminal
  unless retried"* rule and `FAILED → RUNNING` row, its every-claim-carries-an-`approval_ref`
  rule, its claim-before-invocation ordering, its recovery paragraph and its *"We do not claim
  exactly-once execution"* statement — which §3 of this document quotes as its own ground.
  **§5's second scope** is the roster gaining `claim_effect`, `PlanExport` gaining `effects` with
  its `schema_version` moving from 11 to 12, §5's closure rule extending to those rows'
  references and `delete_goal`'s cascade reaching them — the same shape ADR-0249 and ADR-0250
  each took to that enumeration. **§5's compare-and-swap discipline, its commands-not-snapshots
  rule and its local-residency, export-completeness and deletion obligations bind entire**, and
  **§§1-3, §6 and §7 are untouched**. §7's deferral of idempotency keys and `INDETERMINATE`
  resolution is **fired rather than replaced**, which earns no record (§13).
- **Partially supersedes [ADR-0255](0255-the-driver-walks-a-plan-in-dependency-order-claims-each-step-under-its-attempt-and-stops-rather-than-acting-under-an-unfinished-one.md),
  in the identity §7's and §12's at-most-once obligation is stated over, and in nothing else.**
  §7 rules that an effect *"[is] performed **at most once across every plan of that goal**"* and
  §12 states the acceptance requirement over *"a plan whose step would perform **the same
  effect**"*. §1 lands an identity over the **authorised call** and states that two calls meaning
  one thing while spelling it differently carry two keys, so a reader holding only §7 reads its
  obligation more widely than it now holds. **Every other clause of §7 and §12 binds entire** —
  §7's keeps-everything-it-recorded rule, its extension of ADR-0228 §5's not-driven rule, its
  sweep and that sweep's stated residual, its one-plan-per-walk rule and its
  no-licence-to-repeat prohibition; §12's every other entry, both acceptance requirements' other
  halves, and its firing conditions — and §10 books the canonical effect-input identity that
  would close the difference.
- **Partially supersedes [ADR-0192](0192-an-authorisation-is-spent-by-the-act-it-authorises-and-the-trail-gains-an-invocation-row.md),
  in §3's firing clause alone, and in nothing else.** That section rules that the ADR landing
  automated reconciliation *"is fired by a tool contract that offers a **lookup by idempotency
  key** — until a tool can be asked whether a key was already acted on, reconciliation has nothing
  to read."* §3 lands it with no such lookup, on the authorisations ADR-0192 §1 itself rules **not
  spendable** *and* whose recorded decision carries **no `egress_binding`** — a read and a `NATURAL`
  tool, neither of them an egress call — where the call **is** the read. **§1's spendability
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

The owner approved A0–A10 as the working delivery breakdown for the six-phase task
lifecycle (#2255). **A8 is two decisions, and this is the first.** The fit report's A8 row
reads *"The three-case retry policy, reconciliation, `EFFECT_UNRESOLVED`, and
**modify-before-replace**"*, with *"**Takes ADR-0014 §7's idempotency/`INDETERMINATE`-resolution
deferral**"*. This decision takes the reconciliation half — **how an uncertain effect is
resolved, how an unfinished write is finished, and how an effect is kept to at most once across
the plans of one goal**. The retry policy the driver applies **once reconciliation has told it
what happened** is the second, and §10 names it with what fires it.

The requirement register's phase-5 rows are the demand. **R43**: *"A **known failure** and an
**unknown outcome** are different states and are never collapsed."* **R44**: *"An unknown
outcome is reconciled — the effect's status established — **before** any further attempt; a
timeout never becomes a blind retry that duplicates the effect."* **R45**: *"Where the
integration cannot establish the outcome at all, an explicit unknown state is preserved and
reported."* **R46**: *"A completed effect and its evidence survive recovery, restart and
replanning; nothing is automatically replayed."* **R80**: *"No claim is made that local
persistence alone gives exactly-once remote effects; reconciliation is defined and
integration-supported idempotency is used where available."* **R81**: *"A restart during
clarification, approval or recovery preserves task identity, usable evidence, permission state
and completed/uncertain effects, and revalidates what requires it."* And **R41**: *"The actual
response, the identifier the integration supplied, errors and uncertainty are all recorded."*

The report's own assessment is the starting point and is not repeated as a finding: R41, R43,
R45 and R80 **satisfy as stated** on the corpus already, R46 satisfies *"as stated at the
store"* and is **absent across a replan**, and R44 **needs a producer, not a bend** — *"ADR-0014
§7 defers 'Idempotency keys and `INDETERMINATE` resolution … Automated reconciliation of an
`INDETERMINATE` step waits on it', and `Idempotency` already exists in `core/types.py` on the
tool declaration."* This decision is that producer.

The owner's addendum requirement 5 sets the posture: *"Keep 'do not blindly retry an uncertain
effect'; drop 'nothing auto-retries, ever'."* The owner's decision 3 sets what a late answer
gets: *"briefly restate the understanding, recheck evidence and authorization, then proceed"* —
which this decision reaches by making the recheck ADR-0255 §5's, not a second one.

### What ADR-0255 §12 books here, by name

ADR-0255 books seven things to A8 and states **two acceptance requirements** for this lane so it
*"inherit[s] them rather than invent[s] them"*. They are quoted rather than paraphrased, because
they are what this decision is measured against:

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

Two further items arrive with the lane: **#2309**, the evidence-to-claim window, which ADR-0255
§13 makes a prerequisite of the Q4 wiring gate in its own right and §12 assigns to no lane; and
**#2317**, a contended resumed park whose engagement stamp is left unwritten, which ADR-0250
§17's preamble sends *"retry and reconciliation to **A8**"*.

### What the tree holds today, read rather than assumed, at `origin/main` `a0e083ef`

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

A reader holding the corpus without this decision builds a system in which: a replan of a goal
whose first plan already booked a campsite **books it again**, because ADR-0255 §7 states the
obligation and says in terms *"this decision lands no mechanism that could enforce it"*; an
`INDETERMINATE` step **stays `INDETERMINATE` for ever**, because ADR-0014 §4 requires explicit
resolution and no component performs one; an attempt left `RUNNING` beside such a step **stays
`RUNNING`**, so the durable record says the attempt is working while it holds an effect it
cannot account for; a supersession sweep that lost a compare-and-swap **leaves a `PENDING` step
on a plan nobody will drive**; and a user who answered *yes* at the instant their attempt paused
has **spent their one answer on nothing**, with the ruling durable in the trail and no code path
that reads it.

### What this decision is not allowed to settle

Golden rule 5 and ADR-0015 put a `core` contract change behind a ratified ADR of its own, and
this **is** that ADR for the surface §9 names. It is not one for anything else. **It decides no
retry policy** (§10), **no verification** (A10), **no cancellation semantics** (A9), **no user
surface** for anything it records (A9), and **no parallel execution** (ADR-0014 §7's second half
and ADR-0253 §1, untouched).

## Decision

### 1. The effect key: the authorised call's own identity, less the two ids a replan mints afresh

ADR-0255 §7 states the obligation this section makes mechanical, and states honestly that it
could not: *"A step whose effect the goal records as completed or as uncertain is never
dispatched a second time … **Across two plans of one goal this decision lands no mechanism**."*
Its reason is the record that did not exist — *"a goal records no completed effect that a driver
could compare against"*. This section mints that record.

> **Normative.** `core/types.py` gains **`EffectKey`**, a frozen model with `extra="forbid"`
> whose fields are exactly these five, with these annotations and defaults:
> **`tool_id: VisibleIdentifier`**, carrying `ToolDefinition.id`'s own annotation;
> **`parameters_digest: Sha256Hex`**, carrying `PermissionDecision.parameters_digest`'s;
> **`egress_account: BoundAccount | None = None`**; **`egress_endpoint`**, the annotation
> `_EgressBindingBase.transport_endpoint` carries, `| None = None`; and
> **`egress_destinations: tuple[CanonicalDestination, ...] = ()`**. **It carries no sixth field**:
> no step id, no execution id, no plan id, no decision id, no goal id, no instant and no attempt.

> **Normative — a model validator admits exactly two shapes and no mixture.** Either
> **`egress_account` and `egress_endpoint` are both `None` and `egress_destinations` is empty** —
> the no-binding shape — **or both are present and `egress_destinations` is non-empty**. A key
> carrying an endpoint without an account, or destinations without either, is **unconstructable**,
> so one effect cannot be split across two unequal rows by a partial projection. The non-empty
> limb is not a new rule: `canonical_destination_set` is documented as *"therefore **never
> empty**"*, and the validator refuses the shape that declaration already excludes.

> **Normative — the key is what `PermissionDecision.authorises` compares, less the two ids a
> replan mints afresh and less the binding's provenance, and that is the rule a later conjunct is
> read against.** `authorises` compares five values — the tool, `parameters_digest`, `step_id`,
> `execution_id` and `egress_binding`, the last *"compared whole and by value"* (ADR-0150 §9).
> `EffectKey` drops `step_id` and `execution_id`, which describe **where the call was made from**
> and which a re-plan mints anew — ADR-0253 §8's own reason, *"A re-plan mints new step ids"* —
> and takes from the binding **only the three facts that describe where the effect goes**:
> `account`, `transport_endpoint` and the derived `canonical_destination_set`, each declared on
> `_EgressBindingBase` and therefore present on **every** member of the union
> `PermissionDecision.egress_binding` admits. **A later decision that adds a conjunct to
> `authorises`, or a field to the binding, adds the matching field to `EffectKey` in the same
> change unless it states in its own text why that value does not change what the remote system
> does.**

> **Normative — the binding's provenance and authorisation-posture fields are excluded by name,
> and the exclusion errs toward blocking.** `planned_with_external_content`, `coverage`,
> `closed_loop` and `spans` are **not** in the key. The first three record how the call was
> reasoned about rather than what it does, so two replans of one goal that differ only in them
> would otherwise carry two keys and **dispatch the same effect twice** — the failure this
> section exists to stop. `spans` is excluded because `canonical_destination_set` is its
> canonicalisation: ADR-0150 §9 names that set as a thing `authorises` deliberately does *not*
> compare, precisely because *two different decompositions can canonicalise to one destination
> set*, and for effect identity that is the property wanted rather than the one refused.
> **Where the *projection* is wrong it is wrong toward `HELD`, `COMPLETED` or `UNCERTAIN`** —
> two distinct effects treated as one, which stalls a plan — which is the asymmetry ADR-0014 §4
> chooses in every other place it is faced with one. **The key's own reach is narrower than that
> and is stated in the next clause rather than implied by this one.**

> **Normative — what the key recognises is the *same authorised call*, and two calls that mean
> the same thing without being the same call are not recognised.** `parameters_digest` is
> ADR-0021 §1's digest over the canonical encoding of the **supplied** arguments, so two calls
> whose arguments differ in spelling while naming one thing — a recipient written
> `alice@Example.com` in one plan and `alice@example.com` in the next — carry **two** digests and
> therefore **two keys**, and the second is `CLAIMED` and dispatched. **This decision does not
> close that**, and §10 books it with what fires it. **No lane reads the guarantee more widely
> than it is stated**: an effect is performed at most once per goal **per authorised call**,
> which is the identity the permission stage already fixes and the only one this system can
> compute without interpreting a tool's arguments — which ADR-0145 §5 and ADR-0016 §2 both put
> outside `core`.

> **Normative.** `ToolCall` gains **`effect_key`**, a **property** returning `EffectKey | None`,
> derived from the call and **never minted, supplied, configured or carried as a field**. It is
> **`None` if and only if `decision.tool.side_effecting` is false**, and otherwise an `EffectKey`
> built from **`decision.tool.id`**, **`decision.parameters_digest`** and, where
> `decision.egress_binding` is not `None`, that binding's `account`, `transport_endpoint` and
> `canonical_destination_set`.

> **Normative — the `None` limb is `side_effecting` alone, and it is deliberately not
> `ToolDefinition.interrupted_outcome`'s two-limb test.** That test asks what an **interrupted**
> call means and exempts `NATURAL`, because a repeat of one is harmless. **This test asks whether
> an effect exists to be claimed at all**, and ADR-0255 §7's requirement is stated over
> **dispatch** — *"the later step is **not dispatched**"* (§12) — not over what the remote system
> does with a second call. **So a side-effecting `NATURAL` tool has an effect key and is held to
> at-most-once exactly as a `KEYED` or `NONE` one is**, and no lane reads its declaration as an
> exemption from this section.

> **Normative — the two keys are two values and no lane collapses them.**
> `ToolCall.idempotency_key` stays exactly as ADR-0029 §5 derives it — `decision.id` for a
> `KEYED` tool — and is the **tool-facing** key whose property is that it is *"distinct for a
> distinct intent"*. `effect_key` is the **goal-facing** key whose property is the opposite: it
> is **identical across two authorisations of the same concrete call**, which is what lets a
> later plan's step be recognised as the earlier plan's effect. **Neither is computed from the
> other, neither is substituted for the other, and no `ToolInvoker`, tool or component outside
> this system is ever passed `effect_key`** — the one seam it crosses is `PlanStore.claim_effect`
> (§2), and it is never transmitted.

> **Normative — every value is read from the `PermissionDecision` and none from
> `ToolCall.request`.** `PermissionDecision` carries `tool`, `parameters_digest` and
> `egress_binding` as its own fields, so the key needs nothing from the request at all.
> `ToolCall.idempotency_key`'s reason binds here verbatim — the decision's copy is *"the one the
> trail holds, which is the copy a restart reconstructs from"* — and it answers the same threat
> in the same way: ADR-0018 §3 puts a post-construction `__dict__` mutation inside this
> repository's threat model, `ToolCall`'s own docstring records that `frozen=True` *"does nothing
> about `call.__dict__["request"]`"*, and a key derived from the mutable half could be persisted
> for one effect while another was invoked. **Reading the decision closes that**, because the
> decision is the value `ToolInvoker.invoke` re-runs `authorises` against and the value the trail
> holds. ADR-0034 §1's direction of caution binds too: a declaration mutated mid-flight must not
> be able to turn a side-effecting call into one this section exempts.

> **Normative — no digest of the key is minted, and none is pinned.** `EffectKey` is compared
> **by value**, field by field, exactly as `authorises` compares the values it is built from.
> **No clause of this decision composes, concatenates or hashes its fields into a single
> string**, so there is no encoding for two implementations to disagree about and no algorithm to
> pin: `parameters_digest` is ADR-0021 §1's `sha256`, already fixed, and the three egress fields
> are values. **How a store indexes the key is below this contract** and is the implementation's, so
> long as two equal keys are the same row and two unequal keys are not.

**Deriving it rather than declaring it is what makes it a key nobody can get wrong, and the
argument is ADR-0029 §5's, reused rather than re-made.** That section rejected a field for three
reasons — *"It would be a value some caller computed, two callers could compute differently, and
a retry path could forget to carry"* — and all three apply unchanged. A `ToolDefinition` field
saying *"this is the same effect as that one"* would additionally be a **tool author's** claim
about a **goal's** history, which no tool can see.

**And the values it is built from are the values the permission stage already ruled on.**
ADR-0021 §1 binds an approval to the tool, the parameters and the step; `parameters_digest` is
computed on the request rather than accepted from a caller, and ADR-0148 §1 requires the request
a policy rules on to be complete — *"Nothing in it is resolved, canonicalised, defaulted,
expanded or added after `ActionPolicy.decide` has been reached"*. So at the moment the key
exists, the arguments are **fixed, canonical and authorised**, which is the only moment at which
two calls can be compared at all. Reference resolution has already happened (ADR-0253 §6,
ADR-0255 §1), so *"book the campsite the previous step found"* has become a concrete value.

**Taking `authorises`'s own conjuncts rather than inventing a list is what keeps the key honest
as the corpus grows, and the egress binding is why it matters today.** ADR-0150 §9 makes that
binding a conjunct *"compared whole and by value … not by its derived canonical destination set,
not by its account"*, so two calls of one tool with identical parameters and **different
connected accounts** are two different authorised calls — and therefore two different effects.
A key over the tool and the parameters alone would collapse them and refuse the second as a
duplicate of the first. Stating the rule as *"what `authorises` compares, less the two ids"*
makes that answer fall out rather than needing to be remembered, and makes the next conjunct's
obligation explicit rather than a thing a later lane discovers.

**This is not the identity ADR-0255 §7 refused, and the difference is the scope.** That section
warns that *"A driver that compared capability and parameters would be inventing an identity
nobody declared"*. Three things separate this key from that comparison. It is over a
**`ToolDefinition.id`**, not a planner-supplied capability string — the planner's word is never
the key, which is ADR-0249 §7's asymmetry observed rather than cited. It is over the
**canonicalised, resolved arguments a policy ruled on** together with the binding it ruled under,
not over a plan's parameter mapping. And it is scoped to **one goal**, so two different nights
carry two different digests and two different goals never meet at all. What remains is a narrow
and defensible claim: *within one goal, the same tool called with the same concrete arguments
under the same binding is the same effect* — and where a user genuinely wants that effect twice,
§10 names what they do.

### 2. The effect claim: one indivisible write in the store, taken immediately before the step's claim

> **Normative.** `PlanStore` gains **`claim_effect`**, an **`async`** member — it is I/O-bound
> like every other member of that Protocol — whose complete signature is
> **`async def claim_effect(self, *, execution_id: str, step_id: str, effect_key: EffectKey) ->
> EffectClaim`**, taking `execution_id` and `step_id` with the annotations
> `PlanStore.commit_transition`'s neighbours already use for them and returning an
> **`EffectClaim`** and nothing else. The store resolves
> the goal itself, from the execution's plan's `goal_id`, and **no entry point of
> `orchestration` gains a `goal_id` argument for it**. It keeps **at most one row per
> `(goal_id, effect_key)`**, and that row names the `(execution_id, step_id)` currently holding
> the key.

> **Normative.** `core/types.py` gains **`EffectClaim`**, a `StrEnum` valued by lower-cased
> member name and **closed at exactly four members**: `CLAIMED`, `COMPLETED`, `UNCERTAIN` and
> `HELD`. The vocabulary is added to and never renamed.

> **Normative — what each answer means, decided by the stored status of the step the row names
> and by whether that step is this one, in this order and over nothing else.** `claim_effect`
> returns:
>
> 1. **`CLAIMED`**, writing the row, where **no row exists** for the pair.
> 2. Otherwise, read the stored `StepExecution.status` of the step the row names:
>    - **`SUCCEEDED`** → **`COMPLETED`**, writing nothing.
>    - **`RUNNING`** or **`INDETERMINATE`** → **`UNCERTAIN`**, writing nothing.
>    - **`SKIPPED`** → **`CLAIMED`**, re-pointing the row at this step.
>    - **`FAILED`**, **`PENDING`** or **`AWAITING_APPROVAL`** → **`CLAIMED`**, writing nothing,
>      where the row names **this same `(execution_id, step_id)`**; **`HELD`**, writing nothing,
>      where it names a **different** step.
>
> **The second limb is total over `StepStatus`'s seven members, exactly one answer is defined for every input, and the
> same-step case is exactly the three statuses under which the step the row names may still dispatch** —
> a row naming this step at `SUCCEEDED`, `RUNNING` or `INDETERMINATE` answers `COMPLETED` or
> `UNCERTAIN` like any other, because this step has then already acted. **No eighth answer
> exists.**

> **Normative — the references are checked before anything is written, inside the same
> indivisible step.** `claim_effect` **raises `PlanningError` and writes nothing** where no
> execution with `execution_id` is stored, or where `step_id` is not the id of a step of **that**
> execution. **A row is therefore never written that §9's export closure could not satisfy**, and
> a later claim always finds a holder whose status it can read. The check is the store's because
> the store is the only place it can be taken atomically with the write.

> **Normative — the read, the comparison and the write are one indivisible step**, on ADR-0014
> §5's existing compare-and-swap discipline and for ADR-0255 §3's reason: two turns of one
> conversation are not serialized, so **there is no separate read on which a decision is taken**
> before the write. A caller that read the row and then decided would be the race this member
> exists to close.

> **Normative — where it is taken, when it is not taken at all, and what it is not.** The claim is taken **inside the
> stage that holds the authorised `ToolCall`**, after ADR-0037 §2's *decide → record → read back* and **immediately
> before** the `PENDING → RUNNING` (or `AWAITING_APPROVAL → RUNNING`) commit — and **it is not taken at all where
> `effect_key` is `None`** (§1), so a call of a tool that is not `side_effecting` reaches `claim_effect` never, writes
> no row, and is held to nothing by this section. **A side-effecting call always takes it**, whatever its
> `Idempotency`. It is **not a fifth evaluation of the driver's** (ADR-0255 §1), the driver is passed no key and
> computes none, and **`StepRunner.run`, `StepRunner.resume` and `StepExecutor.execute` gain no argument** — the key
> is derived from a value that stage already holds and the goal is resolved by the store.

> **Normative — `StepExecutor` gains no collaborator.** It takes the claim through the
> `PlanStore` it already holds, which is ADR-0058's rule observed rather than bent, and
> `ToolRegistry`, `ActionPolicy` and `AuditTrail` each keep exactly the role they have.

> **Normative — the ordering is effect-claim-then-step-claim, it is fixed rather than left to an implementation, and
> what its failure leaves is stated rather than glossed.** A failure between the two leaves a row naming a step still
> at its entry status. **That step re-claims its own key on the next walk** and dispatches; **every other step of that
> goal carrying the same key is `HELD` until that step is disposed of** — by its own dispatch, or by §4's sweep once
> its plan is superseded — and **where its plan is never superseded and never driven again, that hold does not
> lift**. The reverse order would leave a dispatched effect with **no row at all**, which is the one residual that
> would let a later plan repeat it, so the ordering trades a hold that can stall a plan for a gap that could double an
> act.

> **Normative — a non-`CLAIMED` answer dispatches nothing, commits no transition, and stops the walk.** The stage
> returns the disposition **`Disposition.EFFECT_ALREADY_CLAIMED`** and the step **keeps the status it was entered at**
> — **`PENDING`** where `StepRunner.run` took the claim, **`AWAITING_APPROVAL`** where `StepRunner.resume` did, which
> is the second commit the clause above admits. **It is the entry status rather than `PENDING` because no transition
> is committed**: a resumed step is `AWAITING_APPROVAL` in the store, and naming `PENDING` there would demand a move
> ADR-0014 §4's table does not admit. `ActionPolicy.decide`'s recorded ruling stands in the trail as ADR-0037 §2
> already permits for a claim that did not land — **a resumed step's replayed `ALLOW` therefore stays replayable**
> (§5) — and **no step is moved to `SKIPPED` on this ground, with any `SkipReason`**. ADR-0014 §4's `PENDING →
> SKIPPED` row is untouched and **no lane widens it**.

> **Normative.** `Disposition` gains exactly one member, **`EFFECT_ALREADY_CLAIMED`**. **Which
> `EffectClaim` member produced it is not carried on the disposition**, and what the turn tells
> the user about it is **A9's report** (§10).

> **Normative — a step already disposed of never re-claims, and the at-most-once guarantee is
> stated as the conjunction of this section and ADR-0255 §5.** Within one execution ADR-0037 §6's
> *"`run` enters only at `PENDING`"* is what stops a re-dispatch, and ADR-0255 §5's walk *"passes
> over"* `SUCCEEDED`, `FAILED` and `SKIPPED` without re-dispatching. **Across plans of one goal
> the effect claim is what stops it**, and neither is read as doing the other's work.

**The blocking set is `{SUCCEEDED, RUNNING, INDETERMINATE}` and is written out rather than referred to a private
constant.** `core/types.py` carries `_CLAIMED_STATUSES` over those three **and `FAILED`**, for a different question —
which statuses mean a tool call may have happened at all. `FAILED` is deliberately outside the blocking set, and the
ground is ADR-0034 §1: a `FAILED` step is one where *"nothing could have run under it" is a fact the executor **holds***,
so it answers neither `COMPLETED` nor `UNCERTAIN`. A lane that bound the rule to `_CLAIMED_STATUSES` would call a proven
failure uncertain and refuse the holder's own second attempt — which ADR-0029 §5 admits where *"repeating is safe"* —
and that is R43 read backwards.

**`FAILED` is nonetheless an *occupied* status rather than a free one, and `StepExecutor.execute` is the reason.** That
loop commits `RUNNING → FAILED` through `_run_once` and then, where ADR-0029 §5's two conjuncts both hold, calls
`_claim` again — the tree's one `to_status=StepStatus.RUNNING` construction — so a `FAILED` step is one whose **next act
may be a second dispatch of the same call, inside the same turn**. Re-pointing the row away from such a holder would let
a later plan's step take the key while that retry was still coming, and both would invoke: two claims, on two
`ExecutionState` records, which no compare-and-swap orders against each other. **So `FAILED` takes the shape `PENDING`
takes** — its own holder re-claims it, nothing else does, and the key is freed by that holder being disposed of.

**`RUNNING` is grouped with `INDETERMINATE` rather than with `SUCCEEDED`, and ADR-0014 §4 is why.**
A step durably `RUNNING` is precisely the state that decision calls indistinguishable — *"a crash
between a tool's side effect and the commit of `RUNNING → SUCCEEDED` … cannot, from planning's
vantage point, be distinguished from a crash before the effect"* — and it is the state the
startup scan moves to `INDETERMINATE`. Calling it `COMPLETED` would assert what nobody knows;
calling it `HELD` would invite a caller to wait for a step that may never move. `UNCERTAIN` is the
honest member, and it is the one R45 asks to be preserved.

**`HELD` exists because `PENDING` is a claim in progress rather than an absence, and a `FAILED` holder may still retry.**
A row naming a `PENDING` step was written by a turn that is about to dispatch that step, and two turns of one conversation
are not serialized. Treating `PENDING` as re-claimable would let the second turn take the key and dispatch beside the
first. The cost is stated rather than hidden: a step whose row was written and whose own claim then failed is re-claimable
by **itself** and by nothing else, until the plan holding it is superseded and §4's pass sweeps it to `SKIPPED`, at which
point the key is free again — that is why the sweep and the key are one decision rather than two. **The `FAILED` holder's
cost is larger and this decision does not close it**: §4's sweep reaches `PENDING` and `AWAITING_APPROVAL` steps only, so
a key held by a step that failed for good stays held, and **a later plan of that goal cannot re-perform that effect** —
which §10 books to the decision that owns what follows a failure.

**The store decides it rather than the caller, for ADR-0255 §3's reason and no other.** That
section refuses a caller-supplied revision because *"a check with an extra step"* is a check the
world can move under; the compared value belongs where the write is. The same is true here, and
the same consequence follows: the answer is a **store** answer, so a loser of the race is told it
lost rather than discovering it later. `claim_effect` is a **command, not a snapshot**, on
`PlanStore`'s own stated discipline — it names the change it makes and returns what it decided,
and it takes no whole `ExecutionState` and no whole row back in order to write one.

**What this does not buy, said plainly.** Two turns driving **two steps of one plan** that carry
the same effect key can still each reach `claim_effect`, and the first to write wins while the
second gets `HELD` — which is correct. What it does not close is a plan whose planner emitted the
same concrete call twice **in one `steps` tuple**: the second step is then permanently `HELD` and
the walk stops at it. That is a plan defect, it is visible in the durable record as a `HELD`
disposition rather than as a double booking, and §10 names what would fire a plan-time refusal of
it.

### 3. Resolving an uncertain effect: reconciling with the tool, where the tool declared that can be done

ADR-0014 §4 fixes both routes out of `INDETERMINATE` and neither is a guess: it *"is never
auto-retried and must be resolved explicitly — by reconciling with the tool or by asking the
user"*. ADR-0029 §5 repeats the pair — *"Both remain resolvable by asking the user or by
reconciling with the tool, which is the explicit resolution ADR-0014 §4 requires"*. This section
implements the **first** route and explains why the second is not taken here.

> **Normative — a step is reconcilable exactly where its authorisation is one ADR-0192 §1 rules **not spendable**
> *and* its recorded decision carries **no `egress_binding`** — the complete conjunction, never one half of it,
> wherever this rule is summarised.** That section rules an authorisation spendable *"when the decision's
> `ToolDefinition` is `side_effecting` and its `idempotency` is not `NATURAL`"*, and on any other *"no claim under it
> is ever refused on the ground that it is spent"*. **So an `INDETERMINATE` step is reconcilable if and only if two
> things hold: the `ToolDefinition` recorded for its committed `bound_tool` is not `side_effecting` or has
> `idempotency` `NATURAL`, and the `PermissionDecision` its `approval_ref` names carries no `egress_binding`.** That
> second conjunct is the corpus's own mark for an egress call — the field is *"`None` for every decision about a
> non-egress call"*, which is the same test `ToolInvocationRow.egress_call` is declared over. **Every other
> `INDETERMINATE` step is
> uncheckable** — every side-effecting `KEYED` or `NONE` step, and **every egress step whatever
> its declaration** — for the reasons stated below and booked in §10, and **no `ToolDefinition`
> field is added to say so**: the existing declarations are that test already.

> **Normative — the `KEYED`-inside-its-window route is not taken, and no lane takes it on this
> decision's authority.** `InvocationLedger.claim_invocation` refuses a further **spendable** claim
> where **any** claim under that decision carries the outcome `INDETERMINATE` (ADR-0192 §1), and
> an `INDETERMINATE` step is exactly a step whose ledger claim was completed that way — by the
> seam on a deadline (ADR-0029 §4) or by the recovery scan (ADR-0192 §3). So a `KEYED`
> reconciliation call **cannot reach the tool through `ToolInvoker.invoke`**, and **this decision
> adds no second invocation seam, no reconciliation admission on `InvocationLedger` and no
> parameter to any existing member**. **No implementation of this decision calls a `KEYED` tool
> to reconcile a step**, and §10 carries the route with what fires it.

> **Normative — the reconciliation call is the authorised call rebuilt from durable state, and
> the rebuild is proved rather than trusted.** The `ActionRequest` is rebuilt the way
> `StepRunner` builds one — the step read from the plan, its `resolves` resolved from the stored
> `ExecutionState`, which ADR-0253 §6 makes *"a total function of two values both read from the
> `PlanStore`"* and therefore reproducible after any restart — and the `PermissionDecision` is
> the one the step's `approval_ref` names, read through `AuditTrail.get`. **The rebuilt request
> is then checked against that decision by `PermissionDecision.authorises`, and the call is made
> only where it returns true**; **where it returns false the step stays `INDETERMINATE`, nothing
> is written and no call is made.** So the derived `ToolCall.idempotency_key` is **identical** to
> the first call's, and **no new `ActionPolicy.decide` is taken, no new decision is recorded and
> no new authority is sought.**

> **Normative — it is a reconciliation and not a retry, and the distinction is the tool's own
> declared guarantee.** ADR-0029 §5's exclusion binds verbatim and is **not relaxed**: an
> `INDETERMINATE` outcome is never **auto-retried**. What this section performs is the route
> ADR-0014 §4 names beside that exclusion, and it is available **only** on the declarations under
> which ADR-0192 §1 spends no authorisation at all. **A lane that reads this as licence to
> re-call a side-effecting `Idempotency.NONE` or `KEYED` tool has read the opposite of the
> rule.**

> **Normative — this is automated reconciliation landing without the lookup ADR-0192 §3 names as its trigger, and the
> difference is recorded rather than glossed.** That section rules that *"The ADR that lands automated reconciliation
> is fired by a tool contract that offers a **lookup by idempotency key** — until a tool can be asked whether a key
> was already acted on, reconciliation has nothing to read."* **This decision lands it without one, on the
> non-spendable, non-egress authorisations alone** — the complete conjunction above — and §13 carries the partial
> supersession that fact owes. **The side-effecting `KEYED` case that section was written about is untouched and
> still waits** — for that lookup, or for the ledger admission §10 books, whichever arrives first. **No lane reads
> this clause as licence to reconcile a spendable authorisation.**

> **Normative — what its result writes, and what it does not.** Where the call returns a
> successful `ToolResult`, the step is committed **`INDETERMINATE → SUCCEEDED`**, setting
> `output` from that result and re-stamping `finished_at` at the reconciliation's own instant,
> and **clearing `failure`** as ADR-0039 §2 requires of a `SUCCEEDED` step. **`attempts` is not
> incremented** — the call established what happened and was not an attempt at the effect. Where
> the call returns anything else — a failure, a timeout, an `INDETERMINATE` of its own — **or
> where the call cannot be built at all**, because the step carries no `approval_ref` or the
> decision it names cannot be read, **the step stays `INDETERMINATE`, nothing is written, and
> neither a failed reconciliation nor an unbuildable one is ever read as establishing that the
> effect did not happen.**

> **Normative — at most one reconciliation call per step per turn**, taken inside §4's pass, on
> the turn's own deadline (ADR-0255 §9). **No lane loops, backs off, schedules a second, or
> re-calls a step the same turn already reconciled.**

> **Normative — the reconciliation call takes no step claim, ADR-0014 §4's claim-before-invocation rule is untouched,
> and the concurrency this leaves is bounded rather than denied.** That rule is stated over the **`→ RUNNING`
> transition** — *"The `→ RUNNING` transition is a claim, and must be committed before the tool is invoked"* — and a
> reconciliation **makes no such transition**: the step is `INDETERMINATE`, it stays `INDETERMINATE` until the call
> returns, and §7 admits only `INDETERMINATE → SUCCEEDED` out of it. **No lane invents a claim for it, moves the step
> to `RUNNING` first, or reads this as licence to invoke a `PENDING` step without one.** Two turns engaging one goal
> at once can therefore each make the call, and **that is admitted rather than overlooked**: the authorisations §3
> admits are ones ADR-0192 §1 rules non-spendable *and* whose decision carries no `egress_binding`, where *"no claim
> under it is ever refused on the ground that it is spent"* — the corpus already contemplating the same authorised
> read being made as often as the pipeline needs it — and where ADR-0029 §4 rules a repeat changes nothing. **What is
> not concurrent is the record**: both turns' `→ SUCCEEDED` commits are compare-and-swaps on one `ExecutionState`, so
> **exactly one lands** and the loser writes nothing, which is ADR-0014 §5's discipline doing here what it does
> everywhere else. **ADR-0148 §9's *"There is no egress outside a claimed step"* is not reached at all**, because the
> test above admits no call carrying an egress binding, so nothing this section performs is a transmission through
> the designated seam.

> **Normative — an uncheckable effect stays uncertain, is told once, and is never repeated.** Its
> step stays **`INDETERMINATE`**, its attempt stays **`EFFECT_UNRESOLVED`** (§4), its effect key
> answers **`UNCERTAIN`** to every later claim (§2), and **no lane moves it to `SUCCEEDED`,
> `FAILED` or `SKIPPED`, reconciles it by inference, or dispatches its effect again.** **That the
> user is told, and once, is A9's report** (§10); this decision fixes only that the durable record
> the report reads is preserved, which is R45 exactly.

> **Normative — the user's word does not resolve a step under this decision, and the ground is
> the record a resolution must carry.** ADR-0253 §2 evaluates a producing step's `verifies`
> predicate *"over its `output`"*, so a step committed `SUCCEEDED` is a step whose dependents
> read an output. A user can assert that a booking happened and cannot supply the reservation it
> returned. **So no clause here takes a user's assertion as a step transition**, and the route
> ADR-0014 §4 names second is **booked, not refused** (§10), to the decision that gives it a
> surface and states what `output` such a resolution carries.

**The non-spendable authorisations are the ones under which the corpus both makes a repeat harmless and lets the call
happen, which is why the first conjunct is theirs rather than a new one; the egress conjunct then narrows them
further.** ADR-0029 §4 states the harmlessness in the same breath as the classification this section's subject comes
from — *"A read that timed out changed nothing and there is nothing to be ambiguous about"*, and *"A `NATURAL` tool
is idempotent by nature (ADR-0016 §4), so whether it acted does not change what a repeat does"* — so the call
establishes the effect's status whether or not the first one landed, which is exactly what R44 asks for and why only
one new transition is needed rather than two. `claim_invocation` states the permission: *"An **authorisation is
spendable** when the decision's `ToolDefinition` is `side_effecting` and its `idempotency` is not `NATURAL`"*, and on
any other *"no claim under it is ever refused on the ground that it is spent"*. Such a reconciliation therefore
reaches the callable with **no ledger *contract* change and no signature change** — and **not** with no ledger
*write*: `ToolInvoker.invoke` appends its invocation claim before the callable and its completion after, exactly as
it does for every other call, so the reconciliation's outcome and cost are in the trail like any other act's. What
the non-spendable authorisation buys is that the **further** claim is *admitted*, and ADR-0192 §1's requirement that
every call carry one **binds entire and is relied on here**.

**An egress step is excluded because ADR-0148 §9 rules the seam it would go through, and its two
sentences admit no wording around them.** That section states *"Every transmission through the seam
happens under a committed `→ RUNNING` claim on a plan step … **There is no egress outside a claimed
step**"*, and, of the recovery path by name, *"**A designated seam adds no reconciliation path of
its own**, relaxes none of ADR-0014 §4's treatment of `INDETERMINATE`, and never resolves a pending
attempt by guessing."* §3's call takes **no** `→ RUNNING` claim, by the clause below and on
purpose, so an egress reconciliation would be a transmission outside a claimed step **and** a
reconciliation path a designated seam added — each forbidden on its own. **This decision excludes
the case rather than superseding either sentence**, leaving ADR-0148 entire (§13); the cost is an
uncertain **egress** effect uncheckable here whatever its `Idempotency`, which §10 books with the
shape a later decision would take and with what fires it.

**The read-only case is in the test because the recovery scan does not consult a declaration, and
leaving it out would strand it.** A tool that is not `side_effecting` has **no effect key** (§1),
so nothing blocks a later plan doing that work again — but the step itself would stay
`INDETERMINATE` and its attempt `EFFECT_UNRESOLVED` for ever, because §7 admits no other move out
of that status. A read is the case where the corpus is least equivocal, so refusing to establish
it would be caution spent against the one outcome nobody doubts.

**A side-effecting `KEYED` tool has the harmlessness and not the permission, and that is a fact
about ADR-0192 §1 rather than about the tool.** Inside its window such a call carrying the first
call's key returns the first call's outcome and performs the effect at most once — the better
guarantee of the two. But `claim_invocation` admits a **further** claim only where *"**no** claim
under it carries the outcome `SUCCEEDED` or `INDETERMINATE`"*, and an `INDETERMINATE` step is
precisely a step whose ledger claim was completed that way. That floor was written for a **retry**
and catches a **reconciliation** with it; lifting it belongs in a decision a reviewer reads as
such, so §10 books it, and until then a `KEYED` uncertain effect is uncheckable and un-repeatable —
R45's requirement and not R44's.

**A `NATURAL` step reaches this section only through a crash, and that is why it is in the test at
all.** `ToolDefinition.interrupted_outcome` classifies an interrupted `NATURAL` call as `FAILED`,
so a timeout or a cancellation never produces an `INDETERMINATE` `NATURAL` step. What does is the
startup recovery scan (§6), which moves any step left `RUNNING` by a dead process to
`INDETERMINATE` without consulting a declaration. Leaving `NATURAL` out would therefore strand
exactly those steps — uncertain for ever, and blocked for ever by §1's key — for the sake of a
caution the tool itself declared unnecessary.

**Rebuilding the request rather than storing it is what makes a restart survivable, and the
rebuild is checked rather than assumed.** `ActionRequest.parameters` is not durable: what a
restart holds is the plan, the execution, and the decision the trail keeps with its
`parameters_digest` and its `egress_binding`. ADR-0253 §6 makes the resolution *"a total function
of two values both read from the `PlanStore`"*, so the concrete mapping is reproducible — and
`PermissionDecision.authorises` is the check that it **was** reproduced, comparing the tool, the
digest, the step, the execution and the binding before anything is called. A rebuild that drifted
— a plan edited, a reference whose producer's output changed, a binding no longer available —
fails that comparison and the step stays uncertain, which is the safe direction. This is ADR-0021
§4's resolution invariant applied one seam over, and it is why §3 needs no durable carrier for a
parameter mapping.

**Holding the tool to its window is already a two-sided obligation, so this reads a declaration
rather than trusting one.** ADR-0029 §5 puts both sides in the conformance suites. What this
section adds is a **reader** of the declaration at the one moment it decides something: whether
an uncertain effect can be established at all. The window is read at the instant of the call, on
ADR-0026's clock discipline, from the definition recorded for the **committed `bound_tool`** —
never from a registry lookup that a mutated declaration could answer differently, which is
`interrupted_outcome`'s own stated reason.

**An `Idempotency.NONE` side-effecting tool is where this system's honesty is spent, and it is
spent deliberately.** R80 is satisfied *as stated* on the corpus precisely because ADR-0014 §4 and
ADR-0148 §9 *"both refuse the exactly-once claim"*. Nothing in this decision converts local
persistence into a remote guarantee. What it converts is the **consequence** of not having one:
before, an uncertain effect was a state nothing could resolve and nothing could stop being
repeated; after, it is a state that resolves where the integration supports it, and that is
**durably un-repeatable** where it does not.

### 4. The reconciliation pass: at the start of one turn, over one goal, finishing writes and starting no job

> **Normative.** `orchestration` gains a **reconciliation pass**: a concrete collaborator run
> **inside a turn**, **after that turn has engaged its goal** (ADR-0250 §1) and **before the
> turn's first `Planner.plan` call**, **over that one goal and no other**. It stamps **no
> `AttemptPhase`** (ADR-0249 §6's writer clause), opens **no attempt** (ADR-0249 §5: an attempt
> is opened only by a user act), writes **no `GoalStatus`**, **opens no walk and dispatches no
> `PENDING` step**. **It reaches a dispatch through exactly one of its acts — act 2's replay of
> an authority the trail already holds — and through no other**, and §3's reconciliation call is
> not a dispatch of a step but the remaking of a call already made.

> **Normative — it performs exactly five acts, in this order, and no sixth.** Over the goal the
> turn engaged:
>
> 1. **Complete a supersession sweep.** For every plan of that goal that a stored plan
>    supersedes, each step standing **`PENDING`** or **`AWAITING_APPROVAL`** is committed
>    **`→ SKIPPED`** with **`skip_reason=SUPERSEDED`**, which is ADR-0255 §7's own sweep, from
>    its own two source statuses.
> 2. **Apply a recorded resolution.** For every step standing `AWAITING_APPROVAL` on a plan
>    **no** stored plan supersedes whose binding `AuditTrail.resolution_of` answers: a **`DENY`**
>    commits **`AWAITING_APPROVAL → SKIPPED`** with **`skip_reason=APPROVAL_DENIED`**, naming that
>    decision; an **`ALLOW`** is replayed through `StepRunner.resume` under §5, after ADR-0255
>    §5's three predicates have been re-evaluated and only where every one of them holds. **This
>    act is the only caller of that replay**, and where a predicate refuses, `resume` is not
>    called, nothing is resolved and the step stays parked (ADR-0255 §5).
> 3. **Repair the attempt's state.** For every attempt of that goal whose `state` is **`RUNNING`**
>    and one of whose executions holds a step standing **`INDETERMINATE`**, commit the attempt
>    **`EFFECT_UNRESOLVED`** through `PlanStore.commit_attempt`.
> 4. **Reconcile.** For every **reconcilable** `INDETERMINATE` step of that goal (§3), take one
>    reconciliation call and write what §3 says it writes.
> 5. **Release the attempt.** Where an attempt stands `EFFECT_UNRESOLVED` and **no** step of any
>    of its executions stands `INDETERMINATE` or `RUNNING`, commit it **`RUNNING`** (§7).
>
> **Acts 1 and 2 apply ADR-0255 §6's override**: no step of an `INDETERMINATE` branch and no step
> behind an `INDETERMINATE` step is swept, and a sweep that meets one **is not thereby partial**.

> **Normative — the pass is authorised to complete these writes, and that is stated rather than
> derived.** ADR-0255 §6 and §7 each forbid a lane retrying their partial writes *"from a later
> turn **on its own authority**"* and each names the exception in the next clause — *"repairing
> that residual is A8's"*, *"A8's reconciliation … is the **only** one that may complete a
> sweep"*. **This decision is that authority**, and it is the only one: **no other lane, and no
> implementation of any other decision, completes a sweep, repairs an attempt's state, or
> reconciles a step.**

> **Normative — the pass makes every write as a compare-and-swap and stops at the first that
> loses.** A stale `expected_version` or a store failure ends the pass for that turn; **what
> landed stands, nothing is undone, nothing is retried within the turn**, and the next turn that
> engages the goal runs the pass again over whatever is then residual. **A pass that ends early
> does not fail the turn** — every act it takes is a repair of a record, not a prerequisite of
> the turn's work.

> **Normative — it infers nothing.** `EFFECT_UNRESOLVED` is **written** by act 3 and is never
> derived at read time, which is ADR-0255 §6's prohibition and ADR-0249 §6's writer clause both
> observed. `SUPERSEDED` is committed by act 1 and is never inferred from a plan's `supersedes`
> chain at read time. **No status of any record is computed from another record by any consumer.**

> **Normative — it is bounded by the turn and by the goal, and it is not a background pass.**
> It runs only on a turn the user initiated, only over the goal that turn engaged, only under
> that turn's deadline, and **nothing schedules it, queues it, retries it out of band or runs it
> for a goal no turn engaged.** **No lane reads this section as licence to drive, sweep or
> reconcile outside a turn**, which is ADR-0255 §12's outside-a-turn entry left exactly where it
> stands.

**ADR-0250 §12's clause binds here and is satisfied rather than scoped, and the working is
this.** That decision's prose reads *"no scheduler, no job and no background pass **is added**"*,
and it states it as the consequence of settling an expiry *"at the first operation that reads
it"* — ADR-0244 §10's shape, where the settling work is done by whoever next looks. **This pass
is that shape, not its opposite**: it is the first operation that reads the residual, running
inside an owner-initiated turn over the goal that turn is about, on that turn's own budget.
Nothing is scheduled, nothing polls, nothing wakes, and ADR-0083 §7's *"no job gets new store
surface"* is not reached — `claim_effect` is reached by a dispatch, not by a job. So the clause
is **relied on and not superseded**, and §13 shows that working rather than asserting it.

**A pass rather than a repair folded into each reader is what keeps the writers countable.**
The alternative — each consumer repairing what it happens to notice — would give
`EFFECT_UNRESOLVED` and `SUPERSEDED` as many producers as there are readers, which is the second
authority ADR-0249 §5 refuses for *paused* and ADR-0255 §6 refuses for this state by name. One
pass, five acts, one order, in one place, is what makes *"who wrote this"* answerable.

**And it runs before planning rather than after, because planning is what reads it.** The owner's
decision 3 requires a late answer to *"recheck evidence and authorization, then proceed"*. A
planner handed a goal whose superseded plan still shows a `PENDING` step, or whose attempt still
reads `RUNNING` beside an uncertain effect, is a planner reasoning from a record the system knows
is stale. Running first is also what lets §2's key be free by the time the walk reaches a step
whose predecessor was swept.

### 5. The resolved-but-unapplied answer: the recorded ruling is replayed, and nothing is re-asked

ADR-0255 §12 states the residual and leaves the choice open — *"the step is re-askable or the
answer is re-appliable"*. **This decision takes re-appliable**, and it takes it with the query
ADR-0059 §2 already landed for exactly this.

> **Normative.** **The answer is re-appliable and the step is never re-asked.** No second
> `CONFIRM` is minted for a binding that already carries a resolution, `AuditTrail.record`'s
> single-resolution rule and ADR-0044 §2(b)'s per-binding rule bind **verbatim and untouched**,
> and **no clause of this decision authors any permission record at all.**

> **Normative — `StepRunner.resume` replays a recorded resolution instead of authoring one.**
> Where `AuditTrail.resolution_of(execution_id=…, step_id=…)` returns a decision for the binding,
> `resume` **skips ADR-0037 §4's steps 4 and 5** — it calls **no** `ActionPolicy.resolve` and
> records **nothing** — and proceeds to that section's **step 6** with the returned decision:
> an `ALLOW` is read back and executed, a `DENY` commits `AWAITING_APPROVAL → SKIPPED` with
> `skip_reason=APPROVAL_DENIED`. **Every other step of that sequence is unchanged**, steps 1–3
> included, and `_check_parked`'s binding of the confirmation's tool to the reloaded step's
> `bound_tool` binds entire.

> **Normative — the caller's answer does not override a recorded one.** Where a resolution
> exists, the disposition is **the recorded decision's ruling** and not the `approved` value the
> caller passed. A second answer to an answered binding **decides nothing**, which is ADR-0044
> §2(b)'s refusal *"reaching the caller as an answer instead of as an error"*, in ADR-0198 §3's
> own words.

> **Normative — the replayed dispatch is a dispatch and takes every check one takes, and §4's
> act 2 is its only caller.** ADR-0255 §5's three predicates are re-evaluated before `resume` is
> called with an `ALLOW` — the dependency rule, every member of `when`, and the resolvability of
> every `resolves` — ADR-0255 §3's claim conjuncts bind at the `→ RUNNING` commit, and §2's
> effect claim is taken immediately before it. **A denial is gated on none of them**, exactly as
> ADR-0255 §5 rules. **No walk calls this replay**: ADR-0255 §5's rule that an
> `AWAITING_APPROVAL` step *"stops the walk where it stands"* binds verbatim, which is why the
> replay belongs to a pass that runs **before** the walk and leaves the step disposed of by the
> time one reaches it.

> **Normative — the superseded-plan ground is excluded by name.** Where a stored plan supersedes
> the step's plan, §4's act 1 sweeps that step to `SKIPPED`/`SUPERSEDED` and **the resolution is
> never replayed**, because the approval authorises nothing there (ADR-0255 §3, §7). **No lane
> replays a resolution onto a step of a superseded plan.**

> **Normative — the one-shot approval is spent exactly once, and that is what re-applying buys.**
> The user's answer authorises **one** dispatch; replaying the same recorded `ALLOW` reaches that
> dispatch without a second record, so ADR-0036 §2's unique index is never approached and the
> answer is neither lost nor doubled. **No lane reads a replay as a fresh authority**, and
> ADR-0254 §13's comparison at `ActionPolicy.decide` is taken at the dispatch as it is at every
> dispatch.

**Re-asking was the available alternative and it is rejected on a rule, not a preference.**
ADR-0044 §3 states that where a binding carries a resolution *"the binding is decided and no
further resolution may be recorded"*, and ADR-0198 §3 records that a direct retry *"re-enters
resolution and meets the trail's single-resolution index"*. So re-asking would need either a
second binding for one step — which ADR-0044 §2 forbids by making the binding the unit — or a
relaxation of the single-resolution rule, which would make *"did the user answer this"*
un-answerable. **Neither is a narrowing; both are new rules**, and the mechanism that avoids both
is already on the Protocol.

**This closes #257's first half and leaves its second exactly where ADR-0255 §12 puts it.** #257
names two closures: *"Find the recorded ruling for a parked step"* and *"Make the pair atomic"*.
The first landed as `resolution_of` (ADR-0059 §2) and gets its consumer here. **The second is not
taken** — it *"needs `PlanStore` to accept more than one transition in a commit, a contract change
with a much wider blast radius"* — and §10 carries it with what fires it. All three of #257's
instances close on the first: `resume`/`ALLOW` and `resume`/`DENY` by the replay above, and
`run`/`DENY` — a step left `AWAITING_APPROVAL` under a recorded `DENY` — by §4's act 2, which
reaches it because a `DENY` recorded at `run` and a `DENY` resolving a `CONFIRM` are both
decisions the binding carries.

**And it is driven by §4's act 2 rather than by a new façade method, which is the budget ADR-0059
§2 asks for.** That section rules that driving a stranded binding *"execute[s] and mutate[s] plan
state, so [it] belong[s] to `resume` — which already carries a caller/deployment execution budget
— or to a distinct, explicitly-budgeted recovery operation, **never** to
`pending_confirmations`"*. §4's pass is the second of those: explicitly budgeted by the turn's own
deadline. **`AssistantEngine` gains no member and no enumeration changes** (§9), so ADR-0052's
presentation question is untouched — this decision neither surfaces a stranded park nor changes
what any enumerator returns.

### 6. The startup scan, and the engagement stamp

> **Normative — the startup recovery scan writes no attempt state.** It keeps ADR-0014 §4's
> behaviour entire — it scans `active_executions()`, completes every open invocation claim
> (ADR-0192 §3) and moves a stranded step `RUNNING → INDETERMINATE` — and **writes no
> `AttemptState`, reads no `GoalAttempt`, and takes no reconciliation call.** **It gains no
> collaborator and no argument.**

> **Normative — the attempt is repaired when the goal is next engaged, and not before.** §4's act
> 3 is the producer for the residual the scan leaves, which is the same producer as for the
> residual ADR-0255 §6's second write leaves. **There are exactly two producers of
> `EFFECT_UNRESOLVED` in the corpus after this decision** — the driver, for a step it drove
> (ADR-0255 §6), and §4's act 3 — and **no third is added by any lane.**

> **Normative — the residual #2317 records needs no repair mechanism, and none is added.** A
> resumed park whose `engage_goal` lost its compare-and-swap leaves `last_engaged_at` unmoved;
> **§4's pass does not write it**, because writing it would make the pass a fifth act that
> engages a goal, and ADR-0250 §1 closes that enumeration at four. **The next engagement of that
> goal writes the stamp**, which is ADR-0250 §1's own mechanism doing its own job.

**Giving the scan an attempt would be the wrong shape, and ADR-0255 §12 says why in its own firing
condition.** That entry is *"Fired by the lane that gives the scan an attempt to write to"* — and
this decision declines to be that lane. The scan *"runs outside a turn with no attempt in hand"*;
reaching one would mean walking execution → plan → goal → attempt at startup, for every stranded
step in the store, across every goal, with no user present and no deadline. That is a background
pass in all but name, it is the thing ADR-0250 §12's prose declines, and it would put a **third**
writer on a state ADR-0249 §5 gives one authority. The repair is owed to the **goal's next turn**,
which is the first moment anybody reads the attempt.

**The cost of deferring it is one stale field on a record nobody is reading, and it is bounded.**
Between the restart and the goal's next engagement, an attempt may read `RUNNING` while one of its
steps is `INDETERMINATE`. Nothing dispatches on that: the step's status is *"the authoritative
record of the uncertainty"* (ADR-0255 §6) and it is the value §2's effect claim reads, so the
effect is un-repeatable throughout the interval whatever the attempt says. What the interval costs
is the attempt's own summary being less informative for exactly as long as nobody looks at it.

**#2317 is answered rather than mechanised, and the reason is what the value is for.** ADR-0250 §1
derives focus on every read and stores it nowhere; the issue's own analysis says *"the next
engagement of that goal repairs it; nothing is lost but the ordering of one candidate set"*. A
repair mechanism for a hint that the next read repairs is machinery bought for nothing, and it
would need the pass to take an act ADR-0250 §1 enumerates as a user's. **What would reopen it** is
a measured case in which the stamp stays unwritten **across** turns — which would be a fault in
M3's bounded retry rather than a missing reconciliation act, and would be that lane's to fix.

### 7. After a resolution: no automatic re-drive is added, and the turn's own route is unchanged

ADR-0255 §12 books *"An automatic re-drive of a stopped walk — continuing a plan after an
`INDETERMINATE` step is resolved"* to A8 as *"the lane that resolves an `INDETERMINATE` step and
is the only one with something new to drive on"*. **This decision answers it by adding no route**,
and states why the resolution is nonetheless what makes the branch drivable again.

> **Normative — no automatic re-drive is added, and ADR-0255 §2's closed list stays closed.**
> That section's clause binds verbatim: *"A stopped walk is re-entered by **exactly one**
> route: `StepRunner.resume` answering a park of that plan … **There is no sweep, no timer, no
> queue, no background continuation and no automatic re-drive** of a plan the walk stopped on any
> of the other four triggers. A later turn of the same attempt **plans again** — which produces a
> **new** plan, driven over a **new** execution."* **No clause of this decision re-enters a
> stopped walk, selects a plan for a turn, walks a plan the turn was not handed, or resumes a
> walk over a superseded one**, and ADR-0255 §7's *"one plan is driven per walk, and it is the
> plan the turn holds"* is untouched.

> **Normative — what the resolution buys is the order, not a route.** §4's pass runs **before**
> the turn's first `Planner.plan` call, so a step reconciled to `SUCCEEDED` is `SUCCEEDED` before
> the turn plans and before anything is walked: the planner reads a goal whose uncertain effect
> is settled, the dependents of that step are evaluated under ADR-0253 §2 like any others
> wherever the turn's walk reaches them, and **an effect the resolution established answers
> `COMPLETED` to §2's claim** so a fresh plan repeating it is not dispatched. **No second walk is
> scheduled, no walk is re-entered inside one turn on account of a resolution, and no
> `Planner.plan` call is taken on account of one.**

> **Normative — the attempt returns to `RUNNING` only when nothing is outstanding.** §4's act 5
> commits `EFFECT_UNRESOLVED → RUNNING` **only** where no step of any of that attempt's
> executions stands `INDETERMINATE` or `RUNNING`. `EFFECT_UNRESOLVED` is not terminal (ADR-0249
> §5), so the move is legal; **no lane moves an attempt out of a terminal state**, and **no lane
> moves it to `RUNNING` while an uncertain effect stands.**

> **Normative.** ADR-0014 §4's transition table gains exactly one row —
> **`INDETERMINATE → SUCCEEDED`**, trigger *reconciliation established the effect*, also setting
> `output` and `finished_at` — and **no other**. `INDETERMINATE → FAILED`, `INDETERMINATE →
> RUNNING`, `INDETERMINATE → SKIPPED` and every other move out of that status stay **illegal**,
> and `PlanExecution` refuses each with `PlanningError` as it does today.

**One row rather than two is a consequence of §3's mechanism, not a gap in it.** A reconciliation
that establishes *"the effect did not happen"* would want `INDETERMINATE → FAILED`. Under the one
route §3 admits, that outcome does not arise: a `NATURAL` call that meets no earlier effect
**performs** it, so the two cases §3 calls equivalent both end at `SUCCEEDED`. The
transition that would record a proven non-effect has **no producer**, and adding a row nothing
writes would be the vocabulary-with-no-producer problem ADR-0249 §5 names. §10 carries it: the
decision that takes a second reconciliation route is the decision that adds the row.

**`FAILED` stays terminal-unless-retried and this decision does not reach it.** ADR-0014 §4's *"`FAILED` is terminal
unless retried"* and its `FAILED → RUNNING` row are untouched; **whether and when a `FAILED` step is retried across
turns is the retry policy**, and that is the next ADR's (§10). What this decision settles about `FAILED` is one thing
only: which step may take the key of a row a `FAILED` step holds (§2) — that step itself, so its own retry proceeds,
and no other.

### 8. The evidence-to-claim window is booked, not closed, and the ground is stated

> **Normative.** **This decision does not close the evidence-to-claim window** ADR-0255 §1 states
> and §12 books as #2309, and **no lane reads any clause here as having closed it.** ADR-0255
> §13's second added prerequisite to the Q4 wiring gate therefore **stands undischarged** by this
> decision, and remains a prerequisite in its own right.

> **Normative — what fires it, and what a lane may not do meanwhile.** It is fired by **a
> decision that chooses between the two mechanisms ADR-0255 §12 names** — a value the claim
> carries, or ADR-0252 §6's four tests evaluated inside `commit_transition` — or by **the wiring
> of the first consequential capability**, whichever is first. **No lane adds either mechanism on
> its own authority**, which is ADR-0255 §12's clause binding unchanged.

> **Normative — this decision adds no third prerequisite to that gate**, and the count stays at
> ADR-0255 §13's two. **Its own guarantees are the reconciliation half of the gate's first three**
> and are discharged by the lanes §11 cuts.

**Booking it rather than taking it is a judgement about what the two mechanisms are, and it is
argued rather than asserted.** Both close a window about **authority to act**, not about **an act
already taken**. The first — an evidence token compared by the store — is a new value on
`StepTransition` that ADR-0255 §3's argument against a caller-supplied revision applies to
unchanged. The second puts **a clock and a plan's `when` conditions inside `PlanStore`**, which is
a store that today compares versions and reads plans, and would duplicate the driver's own
predicate in a second place free to disagree with it. Taking either here, inside a decision whose
subject is effects that have already happened, would mean this ADR's review was the review of a
mechanism nobody had reasoned about in its own terms — and ADR-0255 §12 is explicit that the
choice between them *"is a decision of its own"*.

**What holds meanwhile is stated rather than assumed.** ADR-0255 §13's Q4 rule binds: no
consequential capability is wired until the guarantees for its class are implemented and
demonstrated, and the window is one of its named prerequisites. So the interval in which this
decision lands and #2309 stands open is an interval **with no real consequential integration in
it** — which is the same construction ADR-0255 §7 uses for cross-plan at-most-once, and which
this decision now discharges the other half of.

### 9. The `core` surface, the stored shapes, and the wire

> **Normative.** `core/types.py` gains exactly four declarations — **`EffectKey`** (§1),
> **`EffectClaim`** (§2), **`EffectRecord`** (below) and **`ToolCall.effect_key`**, a property
> and **not a `computed_field`** — for `idempotency_key`'s own recorded reason, that a computed
> field enters `model_dump()` and ADR-0018 §4's registration rebuild runs against
> `extra="forbid"`. **`Disposition` gains exactly one member**, `EFFECT_ALREADY_CLAIMED`, and
> **`PlanExport` gains exactly one field**, `effects`.

> **Normative.** `EffectRecord` is a frozen model with `extra="forbid"` whose fields are exactly
> **`goal_id: Identifier`**, carrying the annotation `ActionPlan.goal_id` uses;
> **`key: EffectKey`**; **`execution_id: DurableIdentifier`** and **`step_id: DurableIdentifier`**,
> carrying the annotations `PermissionDecision.execution_id` and `PermissionDecision.step_id` use
> for the same two values; and **`claimed_at`**, a `UtcInstant` **read from the store's own injected clock at each write that
> lands** — so a first claim stamps it, a re-point after a `SKIPPED` holder
> **restamps** it at the new holder's instant, and every no-write outcome (`COMPLETED`,
> `UNCERTAIN`, `HELD`, and the same-step `CLAIMED`) **leaves it exactly as it stands**. **No
> record ever carries an instant earlier than its current holder's claim**, and the clock is
> injected on ADR-0026's discipline rather than read from the wall. It is the row `claim_effect` keeps and the value
> `PlanExport.effects` carries; **it is not returned by `claim_effect`**, which returns an
> `EffectClaim` and nothing else, and **no member of any Protocol takes or returns one** outside
> the export document.

> **Normative.** **`ToolDefinition` gains no field**, **`ActionRequest` gains no field**,
> **`ToolCall` gains no field** (it keeps the two ADR-0029 §2 gives it and the absences that
> section calls *"the design"*), **`StepExecution` gains no field**, **`ExecutionState` gains no
> field**, **`Goal` gains no field**, **`GoalAttempt` gains no field**, and **`StepTransition`
> and `AttemptTransition` gain no field.** The effect row is the store's own record, reached only
> through `claim_effect`.

> **Normative — this is a BREAKING contract change under golden rule 5, and it is flagged here
> rather than inferred from a version number.** `PlanStore` gains exactly one member,
> **`claim_effect`** (§2), so **every implementation and every fake gains it before this
> decision's L2 lands**; the change extends ADR-0014 §5's member enumeration exactly as ADR-0249
> §12's and ADR-0250's additions did, and it is BREAKING for the same reason each of those was.
> **`AuditTrail` gains none** — §5 consumes `resolution_of`, which ADR-0059 §2 already landed. **`ToolInvoker`,
> `ActionPolicy`, `ToolRegistry`, `Planner` and `AssistantEngine` each gain none**, and **no
> Protocol member changes signature.**

> **Normative — the effect rows are the goal's durable data and carry its obligations.**
> `PlanExport` gains **`effects`**, a possibly-empty `tuple[EffectRecord, ...]`; ADR-0014 §5's
> **closure rule extends to it, and it is stated over one holder rather than over three ids** —
> an included row's `execution_id` resolves to an execution in the document, its `step_id` names
> a step **of that execution**, and that execution's plan carries the row's **`goal_id`**, so a
> row cannot name a step that exists only in some other execution while every id still resolves;
> and `PlanExport.schema_version` **moves from 11 to 12**,
> because the document's shape changed and an older reader's `extra="forbid"` must refuse it.
> Rows are **deleted by `delete_goal`'s cascade** with the goal they belong to, **cleared by
> `clear`**, and **stored locally only**. **A row references an execution and a step by id and
> inlines neither**, which is ADR-0014 §3's pattern.

> **Normative — the migration creates the table empty, and the guarantee is delimited to effects
> claimed under this decision.** **No lane reconstructs a row for an execution that predates the
> migration**: doing so would need the tool, digest and binding of a decision the **audit trail**
> holds, and `planning` reaching into `permissions` to build its own rows is what golden rule 1
> forbids. **So an effect performed before the migration is not claimed, is not recognised, and a
> later plan repeating it answers `CLAIMED` and dispatches.** What bounds that is ADR-0255 §13's
> Q4 rule: no consequential capability has been wired into a production deployment, so there is no
> legacy real effect for the gap to expose — the same construction ADR-0253 §3 and ADR-0255 §7
> each use, applied to the one window a migration opens.

> **Normative — the wire.** `Disposition` reaches a client, and ADR-0084 §4 makes adding a member
> additive rather than breaking. **`PROTOCOL_VERSION` is moved once, by L1** (§11), and by no
> other lane of this decision. **No envelope shape changes**, and `ExchangeDisposition` gains a
> mirror member **iff** the archive rendering requires one for the new disposition, which L1
> establishes against the rendering rather than assuming either way.

**The surface is small because the values it needs were already there, and that is the strongest
thing this document can say about itself.** The declaration that says an effect can be checked is
`Idempotency` plus `idempotency_window`, landed by ADR-0016 §4. The key that makes the check
possible is `ToolCall.idempotency_key`, landed by ADR-0029 §5 with recoverability as its stated
purpose. The query that finds an unapplied ruling is `AuditTrail.resolution_of`, landed by
ADR-0059 §2 *for #257 by name*. The statuses that carry uncertainty are `INDETERMINATE` and
`EFFECT_UNRESOLVED`, landed by ADR-0014 §4 and ADR-0249 §5. **What was missing was a goal-scoped
record of which effects a goal has already claimed**, and one store member and one derived
property are the whole of it.

### 10. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them. Each is named so that a reader cannot mistake this ADR's silence for a ruling, and
> each carries the condition that fires it.

- **The retry policy** — the three cases, **modify-before-replace**, and the rule that a known failure and
  integration-supported safe retry are treated differently from an uncertain effect. **A8's second ADR.** This
  decision establishes *what happened*; that one decides *what to do next*, and the owner's addendum requirement 5 is
  its brief: *"Keep 'do not blindly retry an uncertain effect'; drop 'nothing auto-retries, ever'"*, and *"For 'make
  it Sunday', investigate **modifying** the existing reservation first"*. It inherits the vocabulary this decision
  mints — `EffectClaim`'s four members, `Disposition.EFFECT_ALREADY_CLAIMED` and §3's **reconcilable** test. **It does
  not inherit a way to read an effect row**: `claim_effect` returns an `EffectClaim` and nothing else, and §9 puts
  `EffectRecord` on the export document alone, so a modify-first strategy that needs to find the earlier reservation
  adds the bounded lookup it needs and argues for it there rather than inheriting one nobody has reviewed. **It also inherits what §2
  leaves open about a `FAILED` holder**: that row answers `HELD` to every step but the holder's own, and §4's sweep does
  not reach a `FAILED` step, so **a later plan of the goal cannot re-perform an effect whose first attempt proved to
  have failed** — the cost §2 states, taken because `StepExecutor.execute`'s retry makes the alternative a double
  dispatch. That decision is the one that says how ownership passes, and it establishes it **atomically with**
  `FAILED → RUNNING` rather than beside it. **No lane re-points a `FAILED` holder's row on this decision's authority.
  Fired by this ADR landing.**
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
- **A third reconciliation route** — a declared reconciliation read on `ToolDefinition`, or an
  integration that can report an effect's status without performing it. **Not decided.** It would
  also be the producer of the `INDETERMINATE → FAILED` row §7 declines to add. **Fired by an
  integration that offers such a read.**
- **What the user is told** about an uncertain effect, an `EFFECT_ALREADY_CLAIMED` disposition, a
  completed sweep or a replayed answer. **A9**, which is ADR-0249 §13's own division and ADR-0255
  §12's for the same class of question. §3 fixes that the record is preserved and *"told once"* is
  a property of the report; this decision fixes no reply, no phrasing and no channel. **Fired by
  this ADR landing.**
- **A canonical effect-input identity** — one that would recognise two authorised calls whose
  arguments mean the same thing while differing in spelling, so that `alice@Example.com` in one
  plan and `alice@example.com` in the next carried one key rather than two. **Not decided**, and
  §1 states the limit rather than implying it away. Closing it needs a canonicalisation of a
  tool's **arguments**, which is a different thing from the canonicalisation of a **destination**
  ADR-0148 §2 already lands: arguments are arbitrary JSON against a schema ADR-0145 §5 has this
  system **read** and never interpret, so a general one would put a second canonicaliser in
  `core` with no tool-independent rule to follow, and a per-tool one would be a declaration a
  tool author could get wrong in the unsafe direction. **Fired by a measured case in which a
  replan of one goal produces an equivalent-but-differently-spelled call**, or by a decision that
  gives a tool a way to declare its own effect identity and states how a wrong declaration is
  contained.
- **How a user asks for the same effect twice on purpose.** **Not decided.** §2's key refuses a
  second identical concrete call within one goal, and the routes out — a new goal, or arguments
  that differ — are what a user has today. **Fired by a measured case in which a legitimate repeat
  inside one goal is refused.**
- **A plan-time refusal of a plan carrying the same concrete call twice.** **Not decided**, and §2
  states what such a plan does instead: the second step is `HELD` and the walk stops. Refusing it
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

> **Normative.** This decision is implemented in **three lanes**, in this order, each one
> subsystem plus its tests.

- **L1 — the contract and the store.** `core/types.py`'s `EffectKey`, `EffectClaim`,
  `EffectRecord` and `ToolCall.effect_key`, `Disposition`'s member and `PlanExport`'s `effects`
  field with its `schema_version` move; `core/protocols.py`'s `claim_effect`; `planning`'s
  `PlanExecution` transition-table row (§7) and the `PlanStore` implementation with its schema
  migration, export entry and `delete_goal` cascade; the **shared conformance suite** for
  `claim_effect` — including arm 4's two-writer case — and the **canonical fake** in
  `ai_assistant.testing`, which is `CONTRIBUTING.md`'s Protocol triad landing as one unit.
  **L1 moves `PROTOCOL_VERSION`** (§9). Arm 4.
- **L2 — the effect claim at dispatch.** `orchestration`'s executor takes the claim between the
  read-back and the `→ RUNNING` commit, derives the key from the `ToolCall` it holds, and returns
  `EFFECT_ALREADY_CLAIMED` on a non-`CLAIMED` answer. Arms 1–3.
- **L3 — the reconciliation pass, the replay and the attempt's release.** `orchestration`'s pass
  (§4), the `resolution_of` replay in `StepRunner.resume` (§5), the reconciliation call (§3) and
  the release of the attempt (§7). Arms 5–12.

> **Normative — no lane of this decision wires a consequential capability**, registers a booking
> integration, or enables anything in a production deployment. ADR-0255 §13's rule binds entire
> and §12's arms are stated over **controlled fakes** for that reason.

> **Normative — L1 lands before L2 and L2 before L3**, and no later lane's arm is demonstrated
> against an earlier lane's absence. **No lane of this decision implements the retry policy**
> (§10), and a lane that finds itself needing one has left its fence.

### 12. The arms this decision owes

> **Normative.** **Exactly twelve arms** are owed, and the first three are ADR-0255 §12's
> acceptance requirement for at-most-once written as that section demands — *"demonstrated over
> **both** a plan that modifies the earlier one and a plan produced afresh"*, and *"the paired
> case over an **`INDETERMINATE`** first step"*.

1. A plan driven to a **`SUCCEEDED`** step, superseded by a plan that **modifies** it and whose
   step would perform the same effect: the later step is **not dispatched**, `claim_effect`
   answers `COMPLETED`, and the step stands `PENDING` with `EFFECT_ALREADY_CLAIMED`.
2. The same over a plan **produced afresh** rather than by modification.
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
   `planned_with_external_content`, `coverage`, `closed_loop` and two `spans` decompositions that canonicalise alike.
   **`claim_effect` is table-driven over §2's second limb** — each of `StepStatus`'s seven members, crossed with the
   row naming **this** step and a **different** one — and asserts for each both the returned member **and** whether the
   row moved. **The `FAILED` pair is what stops `StepExecutor.execute`'s retry racing a later plan**: this step answers
   `CLAIMED`, a different one `HELD`, and the row moves in neither. It adds: **durable re-pointing** after a `SKIPPED`
   holder, with `claimed_at` restamped; **`claimed_at` preserved** on every no-write outcome, under an injected clock; the
   **refusal** paths — an unknown `execution_id`, and a `step_id` that is not a step of that execution — raising
   `PlanningError` with **no row written**; and **atomicity under contention**, where two writers claim one
   `(goal_id, effect_key)` concurrently, **over both write paths** — **no row**, and an existing **`SKIPPED`** holder
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
7. A supersession sweep that landed one step and not the rest is **completed** by the pass, from
   a **`PENDING`** source status.
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
    attempt returns to **`RUNNING`**, demonstrated over **both** reconcilable declarations — a
    side-effecting **`NATURAL`** tool and a tool that is **not `side_effecting`** — each over a
    request **rebuilt from stored plan and execution state after a restart** and accepted by
    `PermissionDecision.authorises`. **The arm asserts nothing about a later walk**: the reconciled step belongs to
    the earlier execution, ADR-0255 §2 sends the later turn to plan again over a new one (§7), and
    what that turn's plan meets is arms 1–3's subject.
11. **Every way a reconciliation does not resolve a step leaves it exactly as it stood**, in one table: a
    **side-effecting** `Idempotency.NONE` step, a side-effecting **`KEYED`** step, and a step whose recorded decision
    carries an **`egress_binding`** — that last row over a **`NATURAL`** tool, which is the only declaration it can
    carry, because ADR-0148 §8 rules that a tool registered at the seam declares a *"**non-empty `discloses`**"* and
    `core/types.py` refuses *"a tool that discloses data off-device is side-effecting"* — each take **no call**; a
    step whose `approval_ref` is absent, whose decision the trail cannot return, or whose rebuilt request
    `PermissionDecision.authorises` rejects takes **no call**; and a reconcilable step whose call returns a failure, a
    timeout or an `INDETERMINATE` of its own takes **one**, over each of the two declarations §3 admits. In **every**
    row the step stays **`INDETERMINATE`**, `attempts` is **unchanged**, no transition is committed, the attempt stays
    **`EFFECT_UNRESOLVED`**, and **no second call is made in that turn**. **The key is asserted per row rather than
    across them**, because §1 gives one only to a side-effecting tool: a **side-effecting** row's key answers
    **`UNCERTAIN`** to a later plan's claim, and a **non-`side_effecting`** row's `ToolCall.effect_key` is **`None`**
    and `claim_effect` is **never called for it**.
12. The pass's **boundaries**, in one arm. It touches **only the goal the turn engaged**: a
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

> **Normative — no arm of this decision requires a real integration, a scheduler or a restart
> loop.** Arms 1–3 and 10–11 are stated over a controlled `ToolInvoker` whose declaration and
> returned outcome the arm fixes; arm 4 is stated over the store alone; arm 9's residual is
> produced by a store failure the arm injects, and arm 11's rows are driven by a controlled trail
> and invoker rather than by a real integration. **No arm requires a stopped walk to be
> re-entered**, and none asserts that a dependent of a reconciled step runs — §7 adds no route to
> one and ADR-0255 §2's closed list is what it leaves in place.

### 13. Records owed on earlier ADRs, under ADR-0082 §1

**Exactly four documents are partially superseded — ADR-0014 in two scopes, ADR-0255 in one,
ADR-0192 in one and ADR-0037 in one** — and the entries below show the working for those and for each other document a reader would expect
to be superseded and is not. ADR-0082 §1's test is applied to each earlier ADR's **text**: would a
reader holding only it now act differently, or read one of its clauses more widely than it holds?

**ADR-0014 §4 — partially superseded in its transition table, and the scope is on this document's
`Status` line.** §4 states that *"every legal move is enumerated in §4 and enforced by
`PlanExecution`"*, and its table carries no row leaving `INDETERMINATE`. A reader holding only it
builds a `PlanExecution` that raises `PlanningError` on `INDETERMINATE → SUCCEEDED`, so §7's
reconciliation cannot be committed at all. That is ADR-0070 §1's test met and **partial** in
ADR-0070 §3's sense: the scope is the table's enumeration of moves out of an uncertain step and
nothing else. **Every other move in that table binds entire**, and so do §4's every-claim-carries-
an-`approval_ref` rule, its claim-before-invocation ordering, its terminal `SUCCEEDED`/`SKIPPED`
and `FAILED`-unless-retried rule, its recovery paragraph and its *"We do not claim exactly-once
execution"* statement — which this decision quotes as its own ground rather than weakening.

**ADR-0014 §5 — partially superseded in its `PlanStore` member enumeration, its `PlanExport` shape
and `delete_goal`'s cascade, and that scope is on this document's `Status` line too.** §5's code
block enumerates the store's members and its `PlanExport` its document's fields; §9 adds
`claim_effect` to the first and `effects` to the second, extends §5's closure rule to the new
rows' three references, moves `schema_version` from 11 to 12, and reaches those rows with
`delete_goal`'s cascade. A reader holding only §5 builds a store with no member that can claim an
effect and an export document whose `extra="forbid"` refuses the field this decision's rows are
carried in, so ADR-0070 §1's test is met. **This is the third time that enumeration has been
extended in the same shape** — ADR-0249 §12 added five members and the `attempts` field, ADR-0250
added eight and reached `delete_goal`'s cascade to a goal's questions — and it is written the same
way for the same reason. **Every other clause of §5 binds entire and several are the grounds this
decision reasons from**: its compare-and-swap discipline, its commands-not-snapshots rule, and its
local-residency, export-completeness and deletion obligations, which §9 takes for the effect rows.
**§§1-3, §6 and §7 are untouched.**

**ADR-0014 §7's deferral is fired and earns no record, and the distinction is ADR-0082 §1's own.**
That section defers *"Idempotency keys and `INDETERMINATE` resolution … Automated reconciliation
of an `INDETERMINATE` step waits on it"*. Firing a deferral **contradicts no sentence** the
earlier ADR wrote — a reader holding §7 reads that the work is deferred, and it was, until now.
ADR-0082 §1 calls that a **stacked addition**: *"it is recorded in the ADR that makes it, and
nowhere else."* ADR-0255 §17 is the corpus's own precedent, taking four deferrals and recording
none of them — *"what it takes it takes by **firing deferrals** rather than by replacing
clauses"*.

**ADR-0037 §4 — partially superseded in one step of the resume sequence, and the scope is on this
document's `Status` line.** §4's numbered sequence has `resume` always take step 4,
*"`policy.resolve(confirmed, approved=…)`"*, and step 5, *"record the resolving decision with
`resolves` set"*. A reader holding only it builds a `resume` that, on a binding already carrying a
resolution, authors a second one — which ADR-0036 §2's unique index refuses, leaving the strand
#257 describes permanently unrecoverable. **That reader acts differently**, so ADR-0070 §1's test
is met and the supersession is **partial**: the scope is steps 4 and 5 in the case where the
binding already carries a resolution, and nothing else. **Every other clause of ADR-0037 binds
entire and is relied on**: §2's decide → record → read back → claim order, §4's steps 1–3 and 6,
its execution-and-step check and the reason it gives for checking the *stored* execution, §4's
*"the turn never answers on the user's behalf"* rule, and §6's *"This object disposes of one step,
once"* and `PENDING`-only entry.

**ADR-0255 §7 and §12 — partially superseded in the identity their at-most-once obligation is
stated over, and the scope is on this document's `Status` line.** §7 rules that *"an effect a
`SUCCEEDED` and verified step produced, and an effect an `INDETERMINATE` step may have produced,
are each performed **at most once across every plan of that goal**"*, and §12 states the acceptance
requirement over *"a plan whose step would perform **the same effect**"*. §1 lands an identity over
the **authorised call** — the tool, the digest of the supplied arguments, and the binding's reach —
and states in terms that two calls meaning one thing while spelling it differently carry two keys
and the second is dispatched. **A reader holding only ADR-0255 §7 therefore reads its obligation
more widely than it now holds**: they expect A8's mechanism to make the *effect* at most once and
get one that makes the *authorised call* at most once. That is ADR-0070 §1's test met, and
**partial** in ADR-0070 §3's sense — the scope is the identity, and nothing else. **Every other
clause of §7 and §12 binds entire**: §7's keeps-everything-it-recorded rule, its extension of
ADR-0228 §5's not-driven rule, its sweep and the sweep's stated residual, its one-plan-per-walk
rule and its no-licence-to-repeat prohibition; §12's every other entry, its two acceptance
requirements' *other* halves — the modifying-and-fresh demonstration, the paired `INDETERMINATE`
case, and the resolved-but-unapplied answer entire — and its firing conditions. §10 books the
canonical effect-input identity that would close the difference, with what fires it.

**Every other clause of ADR-0255 is relied on and not superseded, and the working is that its own
clauses name this lane.** A reader would expect records on §6 and on §12's residual entries,
because this decision writes `EFFECT_UNRESOLVED` from a later turn and completes a sweep those
sections leave residual. They get none. §6's prohibition reads *"no lane … retries the attempt write from a later turn **on its own
authority**"* and its next clause reads *"repairing that residual is **A8's**"*; §7's reads *"No
lane retries the sweep, resumes it from a later turn"* and its next clause reads *"A8's
reconciliation … is the **only one** that may complete a sweep"*. **A reader holding only ADR-0255
therefore reads exactly what this decision does** — that a named later lane completes them — and
acts no differently. §12's entries are deferrals, fired, which ADR-0082 §1 makes a stacked
addition. And §6's *"the driver is `EFFECT_UNRESOLVED`'s one producer, **for a step it drove**"*
is scoped by its own trailing clause, which §6's very next paragraph confirms by handing the
unwritten case to A8. **Every other clause of ADR-0255 binds entire and is relied on**, §1's four
evaluations and its no-parameter-mapping rule, §2's stop rule and its closed re-entry list, §3's
claim conjuncts, §5's re-walk-from-the-first-position rule and its three re-evaluated predicates,
§9's budget and §13's Q4 rule included.

**ADR-0192 §3 — partially superseded in its firing clause alone, and the scope is on this document's `Status` line.**
That section rules *"The ADR that lands automated reconciliation is fired by a tool contract that offers a **lookup
by idempotency key** — until a tool can be asked whether a key was already acted on, reconciliation has nothing to
read."* §3 of this document lands automated reconciliation **with no such lookup**, on the authorisations ADR-0192 §1
itself rules **not spendable** and whose decision carries **no `egress_binding`**: a read, whose interrupted call
*"changed nothing"*, and a `NATURAL` tool, whose repeat *"does not change what a repeat does"*. There the call **is**
the read — it establishes the effect's status by making it true — so the premise *"reconciliation has nothing to
read"* does not hold, and a reader holding only §3 would wait for a contract this decision does not need. That is
ADR-0070 §1's test met and **partial** in ADR-0070 §3's sense: the scope is that firing clause, and nothing else.

**ADR-0192's other clauses bind entire and several are the grounds this decision reasons from.**
§1's spendability rule is what §3 of this document **cites as its eligibility test** rather than
restating; §1's further-claim enumeration — *"**no** claim under it carries the outcome
`SUCCEEDED` or `INDETERMINATE`"* — binds **verbatim** and is what §10 books the `KEYED` route
behind, so **no clause here widens it, adds an admission, or changes any signature on
`InvocationLedger`**; §3's *"This ADR lands no automated reconciliation of an `INDETERMINATE` act
and mints no idempotency mechanism"* is a statement about ADR-0192 and stays true; its
recovery-scan clause is relied on by §6 and §3 alike; and its spending-on-`INDETERMINATE`
argument — *"the other direction costs a message sent twice"* — is the reason the side-effecting
cases stay uncheckable here.

**ADR-0029 §5 — relied on entire and not superseded, and §3's reconciliation is not a relaxation
of its retry rule.** A reader would expect a record, because §5 says an `INDETERMINATE` outcome is
not auto-retried. It gets none, and the working is this: §5 states two things beside each other —
*"Neither is an `INDETERMINATE` outcome, which ADR-0014 §4 already places outside automatic retry
and which this does not relax"*, and, in the same breath, *"Both remain resolvable by asking the
user or **by reconciling with the tool**, which is the explicit resolution ADR-0014 §4 requires."*
§3 performs the second and leaves the first untouched: no `INDETERMINATE` step is retried under
§5's clause-2 conjunction, and the one call §3 admits is the reconciliation §5 itself names, on
the one declaration under which a repeat is not a second effect. **A reader holding only ADR-0029
§5 already knows reconciliation with the tool is available**, and acts no differently. §5's
derivation of `idempotency_key`, its three properties and its two-sided window obligation are
relied on as the ground of §§1 and 3, and ADR-0029 §4's `interrupted_outcome` rule is relied on as
the ground of §1's `None` limb.

**ADR-0250 §12 — relied on and not superseded, and the no-background-pass clause is satisfied.**
A reader would expect a record, because §4 adds a pass. It gets none. That clause is **unmarked
prose**, it is stated in the form *"no scheduler, no job and no background pass **is added**"*
about that decision's own additions, and it is stated as the **consequence** of ADR-0244 §10's
shape — settling *"at the first operation that reads it"*. §4's pass is that shape: it is the
first operation that reads the residual, it runs inside an owner-initiated turn, over the one goal
that turn engaged, on that turn's deadline, and nothing schedules or wakes it. So a reader holding
ADR-0250 §12 reads no sentence that becomes false, and ADR-0083 §7's *"no job gets new store
surface"* is not reached. **§12's own marked clauses bind entire** — the settle-on-read rule, the
paused-and-resumable rule, `withdraw_clarification`, `SUPERSEDED`'s single producer, the
no-terminal-disposition-from-silence rule and the three user acts that open an attempt — and §4
writes no question state, settles no question and opens no attempt.

**ADR-0148 §9 — relied on entire and not superseded, and the exclusion is why.** A reader would
expect a record, because §3 makes a tool call outside a `→ RUNNING` claim. It gets none: §3's
reconcilable test admits **no** call carrying an `egress_binding`, so nothing here is a
*"transmission through the seam"*, and a reader holding only §9 goes on believing there is no
egress outside a claimed step and that a designated seam adds no reconciliation path of its own —
**both still true after this decision lands**, which is ADR-0070 §1's test failed. §10 books the
case that would need a record, and requires its route to **satisfy** §9 rather than supersede it.

**ADR-0059 §2 — relied on and not superseded, and its own close-out is why.** That section adds
`resolution_of` and says *"the recovery **operation** that consumes it is a later orchestration
wave"* and *"#257 is **unblocked**, not closed here"*. §5 is that wave. A reader holding ADR-0059
§2 expects a consumer to arrive and acts no differently when one does; its budget rule is obeyed
rather than bent (§5), and its refusal-to-present routing and its `pending_confirmations` rule are
untouched, because this decision changes no enumeration. **ADR-0044 §§2–3 are relied on entire**
— the binding as the unit, §2(b)'s one-resolution-per-binding rule and §3's two-step query — and
§5 is stated so that none of them is approached.

**ADR-0253 §5 — relied on and not superseded, and this decision is what its sentence names.** It
rules *"**Nothing in this decision makes an act at-most-once** … Making an intended effect happen
at most once is a different mechanism entirely — it is the idempotency key and the `INDETERMINATE`
reconciliation ADR-0014 §7 defers and **A8** takes."* This is A8, and a reader holding ADR-0253
§5 reads that and acts no differently. **ADR-0253 §2's dependency rule and its `INDETERMINATE`
branch-stopping clause bind entire**, and §7 relies on them for what happens after a resolution.

**The records land in the same change as this document** (ADR-0082 §7): **ADR-0014's, ADR-0255's,
ADR-0192's and ADR-0037's `Status` records**, each carrying its scope with no `ADR-NNNN` token inside the
parentheses under ADR-0070 §4's extraction invariant and each accumulating beside the pairs those
lines already carry, together with **the appended dated note each carries**, which ADR-0082 §1
makes *"the invariant half of the record"*. That is the atomic pair ADR-0082 §7 permits while this
decision stands `Proposed`, and it is why this PR touches **five** files.

### 14. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**A reader acts differently, so this is a decision and not a clarification.** A reader holding the
corpus without it builds a system that re-books a campsite on a replan, that can never resolve an
`INDETERMINATE` step, that leaves an attempt reading `RUNNING` while it holds an effect it cannot
account for, that leaves a `PENDING` step on a plan nobody will drive, and that spends a user's
one *yes* on a dispatch that never happened while the ruling sits durable and unread in the trail.
That is ADR-0070 §1's test met, and a new ADR is the instrument — as it must be in any case, since
`core/types.py` and `core/protocols.py` both change (golden rule 5, ADR-0015).

**It is a partial supersession of exactly four documents in five scopes** (ADR-0070 §3) —
ADR-0014 in §4's transition table **and** in §5's member enumeration, `PlanExport` shape and
`delete_goal` cascade; **ADR-0255** in the identity §7's and §12's at-most-once obligation is
stated over; **ADR-0192** in §3's firing clause; and ADR-0037 in §4's resolution step — and §13
shows the working for each and for the five documents a reader would expect and that get no
record — ADR-0148, ADR-0029, ADR-0250, ADR-0059 and ADR-0253. **Every other ADR it touches is
relied on**, and what it takes it takes by **firing deferrals** rather than by replacing clauses:
ADR-0014 §7's, ADR-0255 §12's seven entries — two of which carry the acceptance requirements stated
there — ADR-0059 §2's named later wave, and ADR-0253 §5's named mechanism.

## Consequences

**An effect becomes a thing the system can recognise, and the record that recognises it is one
row.** *"Has this goal already done this"* is answerable by a store lookup rather than by a
planner's memory or a reviewer's attention, and it is answerable **at the one moment it matters**
— after the arguments are concrete and authorised, and before the claim.

**`INDETERMINATE` stops being a terminal sink for the declarations the corpus lets us call
under.** There are two, not one — a tool that is not `side_effecting`, and a side-effecting tool
declaring `NATURAL` — each only where the decision carries no egress binding. On those an
uncertain effect is established on the goal's next turn, before that turn plans, so whatever it
then plans and walks reads a settled record. Everywhere else — a side-effecting `KEYED` or `NONE`
step, and every egress step — the uncertainty is preserved exactly as R45 asks, and for the
side-effecting ones it — this is the new part — **cannot be repeated**, because the key refuses
every later claim. A non-`side_effecting` step carries no key and needs none.

**The `KEYED` case is the one this decision wanted and could not have, and saying so is part of
it.** `KEYED` inside its window is the better guarantee of the two, and ADR-0192 §1's
further-claim rule — written for a retry — refuses the call that would use it. Until a decision
lifts that floor (§10), the system's best uncertain-effect story is available only where a tool
declared it did not need one.

**Two residuals ADR-0255 left durable are finished by the first turn that looks.** A part-way
sweep and an attempt stranded `RUNNING` are both repaired by a pass that runs on the goal the user
came back to, with no scheduler, no job and no background pass — which is the shape ADR-0250 §12
and ADR-0244 §10 already chose for expiry.

**A user's *yes* stops being losable.** The resolution was already durable and already findable;
what was missing was the one code path that reads it, and §5 is that path. The one-shot approval
is spent once, and neither re-asked nor doubled.

**The cost is that a replan repeating a completed effect stalls rather than double-acting, and
that is the trade this decision makes on purpose.** A step whose key answers `COMPLETED`,
`UNCERTAIN` or `HELD` stays `PENDING` and the walk stops; its dependents wait; and nothing in this
decision inherits the earlier step's output into the later plan. A user will see a plan that does
not finish rather than a booking made twice, and ADR-0014 §4's ground is the one this decision
stands on: *"guessing would not be"* the deterministic answer.

**A second cost is that reconciliation reaches a callable, though never the designated egress
seam.** §3's call is the one act this decision takes outside the store, it is taken only under a
declaration that makes a repeat not a second effect, only where the decision carries **no egress
binding** so ADR-0148 §9 is not reached, only once per step per turn, only over a request rebuilt
from durable state and accepted by `PermissionDecision.authorises`, and only under the authority
already recorded. That is a narrower licence than a retry and it is stated as one; a lane that
widens it has left the fence.

**Revisit when** the retry policy lands (does `EffectClaim` give it what a modify-first strategy
needs?), when a measured case shows a `KEYED` window too short to reconcile within, or an
`Idempotency.NONE` integration that could report its own effect (§10's third reconciliation
route), when the route §10 books for an uncertain **egress**
effect is taken, when a legitimate repeated effect inside one goal is refused (§10), when
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
  own effect cannot discharge an obligation about whether we dispatch. §3 is where `NATURAL`
  earns its exemption, and it earns it there from ADR-0029 §5's own repeating-is-safe test.
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
  interpretation revision. The row is the store's, keyed by the pair that has to be looked up.
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
  branch drivable, and §2's key is what stops the fresh plan repeating the effect.
- **A new `AssistantEngine` member to drive a stranded binding.** Rejected. ADR-0059 §2 permits it
  — *"a new budgeted façade method with its own result contract"* — and it is unnecessary: the
  pass is already explicitly budgeted by the turn, and adding a member would move
  `PROTOCOL_VERSION` for a capability no interface asks for.
- **Making the effect claim a conjunct of `commit_transition`.** Rejected. It would put a second
  refusal ground on the one write every claim goes through, for a value only a side-effecting
  keyed call has, and it would make the claim's failure mode indistinguishable from a stale
  version. A separate member taken immediately before, in the safe order §2 fixes, leaves the
  transition graph exactly as it stands.
- **Taking #2309 here.** Rejected in §8. Both mechanisms close a window about authority to act,
  not about an act already taken, and ADR-0255 §12 states the choice between them is a decision of
  its own.
