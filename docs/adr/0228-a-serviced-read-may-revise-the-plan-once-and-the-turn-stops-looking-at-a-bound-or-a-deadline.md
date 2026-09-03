# 228. A serviced read may revise the plan once, and the turn stops looking at a bound or a deadline

- Status: Proposed
- Date: 2026-09-03
- **Partially supersedes five ADRs, in eight narrowly stated scopes** — five of
  ADR-0226, one of ADR-0158, one of ADR-0014 and one of ADR-0204 — and §15 shows the
  working for every one. The first five:
  [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
  **partially**, in five scopes. §2's **second-emission clause**, *"nor is a second
  emission on the same turn, which is re-planning and is §12's"* — the clause
  `core/protocols.py` carries verbatim on `Planner.plan` as *"never a second request
  on the same turn"*. §6's **one-emission clause**, *"One emission is
  serviced **once** per turn"*, together with the sentence reserving the count's
  movement to *"the ADR that decides it (§12)"* — this is that ADR, and the count
  becomes two. §7's **re-planning prohibition**, *"no lane closes the gap by
  re-calling the planner"*, and, in the same section, the **evaluation-timing
  phrase** *"after servicing"* and the restatement that *"`Planner.plan`'s
  `memories` still carries exactly three groups"*. §8's **trigger clause**, *"a turn
  on which `read_request` is not `None` is a turn the trigger fired on"*, read as a
  test on the one plan a turn produced. And §3's **second-level clause**, *"It does
  not follow the evidence of a record reached by that hop, and no lane adds a second
  level: that is iteration, and it is §12's"* — the deferral is discharged and the
  clause is superseded, in that order and neither instead of the other (§15).
  Everything else of ADR-0226 binds as ratified, and three clauses of it are
  load-bearing here: §3's namer rule, §5's channel scoping and §5's degradation
  posture.
- **And the fifth, sixth and seventh:**
  [ADR-0158](0158-an-episode-may-supplement-the-answering-prompt-and-never-shares-the-belief-budget.md)
  **partially**, in one scope — §5's **three-group clause** as it governs
  `Planner.plan`'s `memories`, and that clause alone: a turn's **second** planner
  call is handed four groups, because the fourth exists by the time it is made. §5's
  grouping-not-ranking caution, its degraded-read clause, its episodic-bound clauses
  and its `Settings` prohibition are untouched, and §4's append-never-interleave rule
  is extended in application and unchanged in text.
  [ADR-0014](0014-planning-model.md) **partially**, in one scope — §2's
  **parenthetical**, *"(the previous one stays referenced by the `ExecutionState`
  that ran it)"*, and nothing else of §2: a plan superseded before anything is driven
  is referenced by no execution, so §5 gives it a reference of its own. §2's
  `frozen=True` rule and its *"Re-planning produces a *new* `ActionPlan` with a new
  `id`"* are **untouched and relied on**.
  [ADR-0204](0204-a-record-carries-whether-the-supply-it-was-produced-over-held-withheld-content.md)
  **partially**, in one scope — §4's **first clause**, further than
  [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
  §13 reached it, and only on a turn that revised: the **plan the turn produces**,
  the **step that plan drives** and the **plan persisted through
  `PlanStore.save_plan`** are the revision's rather than the first plan's, and more
  than one plan is persisted. §4's **second clause is untouched** — no `TurnOutcome`,
  `TurnResult` or `SpokenTurn` member gains, loses or changes meaning here (§12) —
  and §4's narrowing prohibition stands entire.
- **No other ADR is superseded in whole or in part**, and §15 shows the working for
  each one a reader would expect to be — ADR-0037, ADR-0042, ADR-0203, ADR-0208,
  ADR-0211, ADR-0223 and ADR-0227 among them. **ADR-0037 is untouched**, which is the
  one a reader should check first: #1908 and #1952 both expect it to move, and it
  does not, because this decision revises a plan **before anything is driven** and
  leaves *"This object disposes of one step, once"* exactly where it is.
- **Decides a change to `src/ai_assistant/core/types.py`** — one additive defaulted
  field on `ActionPlan`, `supersedes`, with `PlanExport.schema_version` moving to
  **4** and **`PROTOCOL_VERSION` moving to 27**. It adds **no Protocol, no member to
  one and no parameter to any signature**. It **does widen two Protocols' documented
  meaning, and both are flagged as breaking changes under golden rule 5** exactly as
  ADR-0226 §10 flagged its own. `Planner.plan`'s `memories` may carry **four** groups
  on a turn's second call, and a turn may put **two** requests to one planner —
  `core/protocols.py` states both the other way today (*"`memories` still carries
  exactly those three groups"*, and *"never a second request on the same turn — that
  is re-planning, which ADR-0226 §12 defers"*), which is the fourth and fifth
  widenings of that contract's documented meaning and is why §12 binds the lane to
  extend the shared `PlannerContract`. And `PlanStore.save_plan` gains one rejection
  (§5), which is ADR-0014 §5's export promise kept rather than a new decision. **The
  two compatibility facts differ and are stated separately rather than together.**
  The `Planner` widening breaks nothing: no signature moves, `supersedes` is additive
  and defaulted, and every existing implementation conforms exactly as it does today.
  The `PlanStore` widening is **source-compatible but behaviourally breaking** — a
  store that accepts a `supersedes` naming a plan it does not hold no longer
  conforms — so §12 binds the lane to the shared `PlanStore` conformance suite and to
  **both** implementations, not only to the `Planner` one. The version move is the one place this ADR departs from ADR-0226's
  own statement about the same type, and §15 shows why: ADR-0226 §4 and §10 rest on
  *"`ActionPlan` crosses neither `wire/` nor `service/` in the tree"*, and that
  sentence is false against `origin/main` — `TurnOutcome.turn` is a `TurnResult`,
  whose `plan` is an `ActionPlan`, and `TurnOutcome` is what `wire/client.py` returns.
  The gap that leaves behind is not this ADR's to repair and is filed as #1956; what
  this ADR owes is not to inherit the error. **This ADR changes no code.**
  §12 states what the implementing lane owes; nothing implements against it until it
  has merged ([ADR-0015](0015-simplify-the-agent-workflow.md) §5, golden rule 5).

## Context

### Where this comes from

`track:planning` (#1908) is numbered globally, 27 to 30, on the owner's ruling of
2026-09-03; this is **milestone 28**, and #1908's own mapping is *"1→27, 2→28, 3→29,
4→30"*. Milestone 27 is [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md)
and [ADR-0227](0227-a-record-the-citation-hop-reached-renders-its-reply-and-the-test-that-says-so-runs-the-real-renderer.md),
both merged, both implemented, and its exit is **held**: two live probes, #1929 and
#1944, each failed the milestone's headline clause for an independent reason, and the
owner's ruling is owed. This ADR is opened at the owner's word while that exit is
held, because it builds on the ratified envelope shape rather than on the probes'
outcome; its implementation waits for the ruling (§12).

The design note is **#1844**, whose end-state section names the three things a loop
needs beyond the envelope: *"**Re-planning.** A sighted read that changes what is
known must be able to change the plan; today the plan is fixed before any of this and
only the reply benefits"*, *"**An iteration bound and a deadline.** Every hop is a
model round trip on a conversational surface"*, and *"**A loop steered by what it
fetched**"* as the one genuinely new risk. ADR-0226 §12 defers the first two to this
milestone by name and §3 defers the second level of a hop to it in terms. This ADR
takes all three.

### What milestone 27 built, verified against `origin/main` rather than inherited

`LearningLoop._turn` in `src/ai_assistant/orchestration/loop.py` reads the tail,
mints the goal, assembles context, retrieves, supplements, narrows, reads
`ToolRegistry.capabilities()`, and calls `self._planner.plan(...)` **once**. Where
the plan carries a `read_request` and the operation's supply filter is
`BoundedAudienceSupply`, it calls `service_read_request` and does `memories +=
audit.read.records`, then applies the narrowing once, then constructs the
`TurnResult`. There is exactly one `planner.plan(` call site in that module and no
loop around it.

`Engine._run_turn` in `src/ai_assistant/orchestration/engine.py` takes the
`TurnResult` from `self._loop.respond(...)`, and on the path that has a step:
reserves a capacity slot, `save_goal`, `save_plan`, `start_execution`, then
`self._runner.run(state, first.id, ...)` on `turn.plan.steps[0]`, then composes and
captures. On the path with no steps it saves the goal and the plan, composes and
captures, and reserves nothing.

**Two facts about that shape decide this ADR's whole shape.** The planner call
lives *inside* the loop and the step drive lives *above* it in the engine, so a
revision taken **before** anything is driven is a change confined to
`LearningLoop._turn` plus what it hands back; a revision taken **after** a step ran
would have to interleave the two, which is a restructuring of `_run_turn` that
ADR-0042 §3 already named as belonging with the plan-driving stage. And
`save_plan` is called from exactly one place, once per turn, so persisting more than
one plan is a change at that one site rather than a second writer.

### What the replay priced about a second read, and what it did not

The replay on #1844 is milestone 27's evidence base and it speaks to this milestone
directly. Its decisive finding is *"**One read.**"* — reads two and three add
*"10.0pt then 4.6pt on the miss set and 11.3pt then 7.4pt on the hop set"*, which it
calls *"real, sharply diminishing, and nothing needing re-planning"*, and it concludes
that the envelope is *"a **refinement, not a different execution model**"*.

**That sentence is evidence against this mechanism on the axis it measured, and this
ADR states it rather than burying it.** A second read is worth about ten points of
reach on the population where the first read missed, and a third is worth half that.
Read as a retrieval argument, milestone 28 buys the smaller half of an already small
thing.

**What the replay could not price is the axis #1908's charter says the exit is on.**
It drove `retrieve_for` over stored corpora and scored answers; there is no act, no
step and no tool anywhere in it. So it has nothing to say about the case this ADR
exists for: a plan whose **step's parameters** cannot be filled until something has
been read. Today those parameters are fixed before the first read fires, so a turn
that needs to look something up in order to know *what to do* cannot do it — the
plan is complete before the loop has looked. That is a task-capability claim, it is
the one #1908 writes the caution for (*"do not justify the loop by memory-benchmark
numbers"*, *"Exits are task-shaped, not retrieval-shaped"*), and it is the
justification this ADR rests on.

**The retrieval figure is still what sets the bound.** Ten points at read two and
four and a half at read three is exactly the shape that says *one* revision and not
three, and §3 takes it as the reason rather than reaching for a round number.

### The charter's caution, and this ADR's honest justification

#1908 requires that a milestone justify itself by task capability. This one does:

- **A dependent parameter.** *"Email Ana the address of the place we went to last
  month"* is one act whose argument is a memory lookup. Today the planner names the
  step before any sighted read has happened, so it either declines, guesses, or plans
  a step whose parameters are wrong; ADR-0176 §7 admits the model-judgement residue
  and ADR-0170 §6's account reports what happened, but nothing makes the turn work.
  With one revision the read fires, the second plan carries the value, and the turn
  completes without the user re-asking.
- **A judged insufficiency that a first read only partly answers.** #1929's probe is
  the shape: the planner is shown a belief that *summarises* an act and answers a
  question about the act's *content*. A first hop that reaches the wrong record is a
  turn that ends wrong today; with a revision the planner sees what came back and may
  ask again — once.

**And the honest cost is stated in the same breath.** A revision is a second model
round trip on a conversational surface, on up to 13.6% of turns if the live fire rate
matches the replay's. §4 is why that is bounded in time as well as in count, and §9
is where the rate of each guard becomes a number rather than a judgement.

### Claims in the framing that do not survive contact with the tree

Stated because each was carried into this lane's brief or into #1952, and each would
have produced a wrong citation, a wrong scope record or a wrong design.

1. **#242 is not "drive step 2".** #1844's relationship section says *"#242 —
   necessary but not sufficient for the loop"* and ADR-0226 §12 carries the citation
   forward as *"(#1908 milestone 2, #242)"*. #242 is *"orchestration: a parked CONFIRM
   loses its decision id across a restart"*, closed, and its two candidate remedies
   are an `approval_ref` on a transition and a by-step query on `AuditTrail`. It has
   nothing to do with re-planning. This ADR cites it not at all, and neither the
   deferral it appears in nor anything else about ADR-0226 §12 turns on it.
2. **ADR-0037 is not superseded by this decision.** #1908 says milestone 28
   *"Partially supersedes plan-once in ADR-0014/ADR-0037"* and #1952 repeats it.
   ADR-0037's clauses are *"This object disposes of one step, once"* and *"`StepRunner`
   does not drive a whole plan."* Both are about the step runner and both are true
   after this ADR: the engine still drives one step, and it is the **revised** plan's
   first step. §15 shows the working. What would move ADR-0037 is a plan-driving stage,
   which this ADR defers by name in §14.
3. **`ActionPlan` does cross `wire/`.** ADR-0226 §4 and §10 state that
   *"`ActionPlan` crosses neither `wire/` nor `service/` in the tree"* and bind their
   lanes not to move `PROTOCOL_VERSION` on that ground. Against `origin/main`:
   `TurnOutcome.turn` is `TurnResult | None`, `TurnResult.plan` is an `ActionPlan`,
   `TurnOutcome` is the return type of `wire/client.py`'s `converse` and `resume`, and
   `wire/codec.py`'s `project` renders a model with a bare `value.model_dump()` —
   every field, defaults included. `ActionPlan`, `TurnResult` and `TurnOutcome` all set
   `ConfigDict(extra="forbid", ...)`, which is the property `wire/envelope.py`'s own
   log turns on: it records a bump because *"an older client handed a `TurnOutcome`
   carrying `reply` fails"*, and it distinguishes ADR-0213 §11's no-bump ruling for a
   defaulted addition on the express ground that *"Neither type sets `extra="forbid"`,
   so no decode fails in either direction"*. §6 takes the consequence for this ADR's
   own field; the state ADR-0226's field is already in is a defect, is not this ADR's
   to repair, and is filed as its own issue.
4. **ADR-0226 §12's deferral of a per-surface deadline names it as milestone 2's, and
   §6's non-configurability clause names the ADR that may move the count.** Both are
   this one. §12's entry reads *"**A second serviced emission, a configurable read
   count, or a per-surface deadline.** #1908 names the deadline as milestone 2's — *"a
   voice turn cannot afford three round trips"* — and §6 fixes the count at one until
   an ADR moves it."* This ADR moves the count and decides the deadline; it does
   **not** make the count configurable, and §3 says why.
5. **A `Goal` is not turn-scoped, so `goal_id` cannot carry the revision chain.**
   ADR-0014 §1 is explicit that *"a goal ('relocate to Lisbon in September') outlives
   any one conversation"*. `LearningLoop._goal_from` mints one per turn today, but a
   design resting the audit on that would rest it on an implementation detail the
   contract contradicts. §5 adds the link to the plan rather than inferring it from
   the goal.

### What is not in dispute, and is used as given

ADR-0226 §5's channel scoping: a request is not serviced on an operation whose output
channel's audience is unbounded, so no turn on such an operation has anything to
revise over. ADR-0226 §5's degradation posture: *"a failed **or partial** read leaves
the supply as planning saw it"*. ADR-0226 §6's budget of ten, its hop-first
precedence and its two-label cap. ADR-0226 §3's namer rule and its ordinal labelling,
whose whole text is stated over *"the very sequence it passed on this call"*.
ADR-0208 §1's scoping sentence, *"One site is not one call."* And ADR-0014 §2's
frozen plan, which this decision relies on rather than moves.

### An honest statement of what this ADR is not allowed to settle

It does not settle the plan-driving stage, and therefore does not deliver a turn in
which a second `PlanStep` runs; §14 defers it with what fires it and §15 says why
ADR-0037 is untouched. It does not settle decomposition — several asks of one kind —
and §14 says what would fire it. It does not settle whether a revision may follow a
**driven** step's output, which is the harder half and is the plan-driving stage's.
It adds no kind to ADR-0226 §2's enumeration and takes no position on the outward
fetch. It does not repair #1929's trigger or ADR-0226's `PROTOCOL_VERSION` gap. And
it does not measure itself: §9's raised audit is the instrument, exactly as ADR-0226
§8 made the fire rate one.

## Decision

### 1. A revision is a second plan, made over the supply the first plan's read produced

> **Normative.** On a turn that serviced a read request, the loop may call the
> planner a **second time**, over the same goal and the same assembled context, and
> over the supply **as it stands after that servicing** — the three groups the first
> call saw and the fourth group the servicing appended. The plan that call returns is
> the turn's **revision**.

> **Normative.** A revision is a **new `ActionPlan` with a new `id`**, produced by
> the planner in the ordinary way. **A plan's decision content is authored at the
> `Planner.plan` seam and nowhere else**: no implementation mutates a plan in place,
> rebuilds one from another's fields, or authors or edits a plan's `id`, `goal_id`,
> `steps`, `rationale` or `read_request` anywhere but there. The **one** field any
> other component ever sets is `supersedes`, which §5 gives to the loop and which is
> not a decision the planner is in a position to make.
> [ADR-0014](0014-planning-model.md) §2's `frozen=True` and its rule that
> *"Re-planning produces a *new* `ActionPlan` with a new `id`"* bind unchanged and are
> what this section is built on.

> **Normative.** The revision carries the **same `goal_id`** as the plan it replaces.
> The goal is minted once per turn from the user's unrewritten words and nothing about
> it changed; a second goal would make one turn look like two in every store that
> holds goals.

> **Normative.** The **context is assembled once per turn** and the second call
> receives the same `CurrentContext`. No lane adds a second `ContextProvider` read,
> a second conversation-tail read, a second retrieval or a second episodic
> supplement: the three groups of §7 are read exactly once per turn, and what a
> revision plans over that the first plan did not is the fourth group and nothing
> else.

> **Normative.** The **capability vocabulary is read again, immediately before each
> planner call**, from the same registry, exactly as
> [ADR-0211](0211-the-planner-is-told-which-capabilities-exist-and-an-act-nothing-advertises-is-declined.md)
> §3 requires — so the plan the turn drives is judged against the vocabulary as it
> stood immediately before the call that produced it. ADR-0211 is applied here and
> not moved (§15).

**The revision is a plan and not a patch, and that is the whole of why the audit
survives.** ADR-0014 §2's argument is that `frozen=True` *"is what makes the plan an
auditable record of a decision"*, and the question *"what did the system decide to do,
and when"* has two answers on a turn that revised. A design that edited the first
plan would have one answer and a lie about it; a design that produced a second plan
has two records and an order. Producing it at the `Planner.plan` seam is what makes
it a decision rather than a derivation: the second plan is the model's judgement over
a wider supply, which is the mechanism, and a plan assembled in code from the first
one's parts would be neither.

**Nothing else about the turn is re-run, and the restraint is deliberate.** The
conversation tail, the retrieval and the episodic supplement are the turn's blind
reads; re-running them would return the same records for the same query and would put
a second `MemoryStore` read on the turn path for nothing. The context is the
situational *"right now"* and a turn is not long enough for it to have moved.
Re-reading the capability vocabulary is the one exception, and it is not an exception
to this section's restraint but ADR-0211 §3 applied as written: a plan judged against
a vocabulary read before a *different* call is exactly what §3 exists to prevent.

### 2. What fires a revision: seven conditions, and all of them

> **Normative.** The loop makes a second planner call on a turn if and only if **all**
> of the following hold. Each is a fact the turn already has in hand; none is a
> setting, and none is a judgement.

> **Normative.** (a) The turn's operation declares a **planning budget** (§4). An
> operation that declares none does not iterate, and no implementation reads an
> absent declaration as a default, as unknown-and-therefore-permitted, or as a case
> to decide at run time from anything other than a declaration.

> **Normative.** (b) The plan carried a `read_request` — the trigger fired
> (ADR-0226 §8).

> **Normative.** (c) The request was **serviced** rather than declined under
> ADR-0226 §5's channel scoping.

> **Normative.** (d) The servicing **completed**. A servicing that failed or was
> partial leaves the supply as planning saw it (ADR-0226 §5), so there is nothing new
> to plan over and a second call would be handed the first call's own input.

> **Normative.** (e) The servicing returned **at least one record the supply did not
> already hold**, counted after ADR-0226 §7's deduplication. A servicing whose every
> record was deduplicated out leaves the supply byte-identical, and a planner called
> twice over one input is being asked the same question twice at the price of a model
> round trip.

> **Normative.** (f) The turn has made fewer planner calls than §3's bound.

> **Normative.** (g) The turn is **within its operation's planning budget** at the
> moment the check is made (§4).

> **Normative.** Where any condition fails, the turn proceeds with the plan it has,
> exactly as it does today. No implementation retries a failed servicing, widens a
> request, re-asks the planner on a different prompt, or substitutes a read of its own
> for one the planner did not ask for.

**Every condition is mechanical, and that is what keeps the second call from becoming
a policy.** ADR-0226 §8 rules that *"No lane makes the trigger's firing conditional on
a setting, a channel, a surface or a deployment flag"*, and a revision gated on
anything a deployment tunes would make the second emission's rate a property of the
configuration rather than of the planner. (a) and (g) are the two that key on the
operation, and they gate the **iteration** rather than the emission — the planner is
never told, so §9's fire rate stays a reading of the planner.

**(e) is the condition that pays for itself and it is worth stating why it is not
merely thrift.** A sighted query that returns only records already in the supply is
common — the pre-servicing supply is thirty episodes and a full belief budget — and a
second planner call over an unchanged prompt is not just wasted spend but a *wrong*
instrument reading: §9's iteration rate would count a turn that learned nothing as a
turn that looked again. Making the condition the arrival of new material keeps the
number honest.

**And (d) follows ADR-0226 §5's all-or-nothing posture rather than softening it.** A
partial servicing on that ADR's terms returned nothing to the turn; a revision fired
on one would be a second plan over a supply the corpus says the turn never received.

### 3. The bound is two planner calls, and it is not configurable

> **Normative.** A turn makes **at most two** calls to `Planner.plan`. A turn that
> revises therefore takes **one** revision and no more, and no implementation,
> setting, deployment flag or later lane makes the figure configurable or raises it
> without the ADR that decides it.

> **Normative.** The **second plan's request, where it carries one, is serviced**
> under ADR-0226 §5, §6 and §7 exactly as the first plan's is — and no third planner
> call follows it. Its yield reaches the reply and no plan, which is precisely
> milestone 27's own shape and is what ADR-0226 §7 rules when it says that a turn
> composing over more than the planner saw *"is the mechanism and not a side
> effect"*.

> **Normative.** A turn that reaches the bound with its planner still asking — a
> second plan carrying a `read_request` — is recorded as having stopped at the bound
> (§9) and tells the composing stage so (§10).

**Two is read off the replay rather than chosen for tidiness.** Its measured shape is
*"10.0pt then 4.6pt on the miss set and 11.3pt then 7.4pt on the hop set"*: the second
read is worth roughly twice the third, and the third is worth roughly a fifth of the
first. A bound of two spends one extra model round trip where the evidence says the
return is largest and stops where the evidence says it halves. A bound of three would
double the worst-case latency of a conversational turn for the smaller half of a
diminishing series.

**Servicing the second plan's request rather than suppressing it is the cheaper and
the more honest arm.** It costs no model call — the emission already exists — and
discarding it would throw away a read the planner asked for on a turn where the
system had already decided to spend. It also keeps the bound's meaning simple: what
is bounded is how many times the system **plans**, not how many times it reads, and
the two figures differ by at most one.

**Not configurable, for ADR-0226 §6's reason applied one level up.** That section
fixes the read count at one and reserves its movement to *"the ADR that decides it"*
precisely so that a deployment cannot quietly buy reach with latency. The same
argument holds for the plan count, and it holds harder: a plan count is a count of
model calls, so a configurable one is a configurable per-turn cost with no ceiling
anyone reviewed.

### 4. The planning budget is declared per operation, and an operation that declares none does not iterate

> **Normative.** Each conversational operation declares a **planning budget**: a
> duration, from the turn's entry into the loop, within which an additional planner
> call may be **started**. `converse` and `converse_streaming` declare **PT20S**.
> `converse_spoken` declares **none**. An operation that declares none does not
> iterate, whatever its audience.

> **Normative.** The budget is checked with the loop's **injected clock**,
> immediately before each additional planner call and at no other point. An
> additional call is admitted **only while the elapsed time is strictly less than the
> budget**: at exactly the budget, and beyond it, the turn stops and records **budget
> reached**. The boundary instant is spent, not available.

> **Normative.** It is a gate on **starting** an iteration and never a cancellation
> of one in flight: a planner call already begun runs to its own completion, and a
> turn's total duration may therefore exceed its budget by one planner call and one
> servicing. No lane abandons, cancels or times out a planner call on the strength of
> this section.

> **Normative.** The budget is **not a `Settings` value**, not a deployment flag and
> not a per-request parameter. The figures above are fixed here and move only by the
> ADR that moves them, exactly as ADR-0226 §6's ten and this ADR's two do.

> **Normative.** The budget is keyed on the **operation** and never on the channel's
> audience. ADR-0199 §1's audience decides whether a request is serviced at all
> (ADR-0226 §5); it does not decide how long a turn may spend planning, and no lane
> derives one from the other.

**The deadline exists now rather than later because the property that keeps voice out
of iteration today is an accident of which devices are declared.** ADR-0226 §5 refuses
to service a request on an operation whose output channel's audience is unbounded, and
`converse_spoken` is such an operation, so no spoken turn iterates. But ADR-0199 §1
declares an audience **bounded** when what the channel emits reaches a person *"only
through an act of that person's own — being positioned at and looking at a rendered
surface, **or wearing the device that emits**"*. A worn earpiece is a bounded-audience
channel by that clause, and it is the surface #1908's caution is written about: *"a
voice turn cannot afford three round trips"*. The day such a spoke is declared, the
channel scoping stops protecting it and only a declared budget does. Building the
guard when the case is hypothetical is cheaper than discovering it when it is not.

**Keyed on the operation because two operations of one audience have different latency
tolerances.** `converse`, `converse_streaming` and a future worn-earpiece operation
would all be bounded-audience, and would tolerate very different waits. Audience is
the right key for *what may be said* and the wrong one for *how long a user waits*;
ADR-0199 §1's own argument — *"Audience rather than modality, because 'voice' is not
one trust level"* — is a warning against overloading a property, not a licence to
overload this one.

**The boundary is closed at the budget because §4 is a fail-closed clause
throughout.** An undeclared budget iterates not at all; a budget already spent does
not buy one more call. Leaving equality to the implementation would let two conforming
loops differ on identical input — one spending a model call the other refuses, with a
different reply, a different cost and a different audit record — over a reading of the
word *"within"*, and an injected clock makes equality an ordinary case in a test
rather than a measure-zero curiosity. §13's third test asserts it.

**Twenty seconds is a judged figure and is labelled as one.** Nothing in this
repository measures a planner round trip, and this ADR does not invent a measurement:
the count in §3 is meant to be the binding guard in the ordinary case and the budget
to be the tail guard for a turn whose first phase already ran long. §9 records which
guard stopped each turn, so *"how often does the budget actually fire"* becomes a
number from the first deploy — which is ADR-0226 §8's posture, and the reason a figure
this soft is safe to fix here rather than defer.

**Undeclared means no iteration, which is ADR-0199 §1's direction taken for its own
reason.** That clause rules that *"A channel whose audience is not declared has an
**unbounded** audience for every purpose of this ADR"*, because the permissive default
puts the burden on the party who forgot. The same holds here: a lane that adds an
operation and forgets to price it should get the turn the system already has, not a
second model call nobody budgeted.

### 5. Every plan the turn produced is persisted, and the chain is durable

> **Normative.** `ActionPlan` gains one field, `supersedes: Identifier | None`,
> defaulting to `None`. On a revision it carries the `id` of the plan it replaces; on
> every other plan it is `None`, which means **this plan replaced nothing**. No
> implementation reads `None` as an error or as an unknown.

> **Normative.** **The loop sets it, and the planner never does.** On **every** plan
> a planner returns, the loop takes the field for its own: it discards any value the
> plan came back carrying, and then, on a revision and only on a revision, sets it to
> the predecessor's `id`. Every other field is **exactly as the planner returned
> it**. The loop does this **once** per plan, immediately on return and before any
> other component observes it; there is never a moment at which a component other
> than the loop holds a plan whose `supersedes` is the planner's, and no lane sets,
> clears or re-sets the field anywhere else.

> **Normative.** A value the planner supplied is **discarded silently** — not an
> error, not a park, not a degradation of the turn, and not a count in §9's record.
> ADR-0226 §3 takes the same posture for a label a model invents; this is that
> posture on the one field of a plan the planner does not own.

> **Normative.** **No plan identifier is rendered to a model and none is accepted
> from one.** No lane puts a predecessor's `id` in a prompt, adds a parameter to
> `Planner.plan` to carry one, or reads one out of model output. `Identifier` admits
> any non-blank encodable string, so an id a model returned would be an unprovenanced
> value in a durable audit record — which is the ground ADR-0226 §9 refused to log
> `ActionPlan.id` on, applied here to a field that would then be *written* rather
> than merely logged.

> **Normative.** **`PlanStore.save_plan` refuses a plan whose `supersedes` does not
> resolve** — one naming a plan the store does not hold, one naming the saving plan's
> own `id`, and one naming a plan under a different `goal_id` are each rejected as an
> unknown goal already is, with the same error class. This is ADR-0014 §5's export
> promise kept at write time rather than a new invariant (below).

> **Normative.** **`PlanExport`'s reference closure covers `supersedes`.** ADR-0014
> §5 rules that an export is *"complete and internally consistent: every
> `goal_id`/`plan_id` referenced by an included record resolves within the same
> export"*, and `supersedes` is a `plan_id` referenced by an included record. A
> document whose `supersedes` names a plan the document does not carry does not
> validate as a `PlanExport` at all. No lane reads the existing validator's silence
> as permission.

> **Normative.** **Every plan a turn produced is persisted through
> `PlanStore.save_plan`**, oldest first, at the **one site that persists a plan
> today** — so a turn that persists a plan at all persists all of them. Persistence
> order is oldest-first, so no partially-persisted turn leaves a `supersedes`
> pointing at a plan the store does not hold.

> **Normative.** **A turn that ends before that site persists nothing, exactly as it
> does today**, and no lane adds a second persistence site, gives `LearningLoop` a
> `PlanStore`, or carries a plan out of a failing turn in order to write it. A turn
> whose second planner call raises, one rejected for capacity and one that fails
> before the planner is reached are alike in this and were alike before this ADR.
> What such a turn still owes is §9's record, which ADR-0226 §9 conditions on
> nothing.

> **Normative.** **Every plan of the turn is persisted before anything is driven.**
> The whole sequence of `save_plan` calls precedes `start_execution`, so a turn whose
> second `save_plan` raises has driven nothing: no execution is open, no capacity slot
> is spent on a step and no side effect has been reached. No lane interleaves
> persisting a plan with driving one.

> **Normative.** A superseded plan **drives nothing**. It starts no execution, reaches
> no `StepRunner`, no `ActionPolicy` and no `StepExecutor`, takes no step-execution
> capacity slot, and its steps are never selected, ruled on or run. Exactly one plan
> of a turn is driven and it is the last.

> **Normative.** This adds **no failure mode and no degradation posture**. A
> `save_plan` that raises on a superseded plan fails the turn exactly as one raising
> on any other plan does today; no lane swallows it, and ADR-0226 §9's audit still
> emits, because it is *"conditioned on nothing"*. A turn whose first plan persisted
> and whose second raised leaves a plan with no successor, which is a complete record
> of what that turn decided and is not a dangling reference: the link points
> backwards.

> **Normative.** **`PlanExport.schema_version` becomes `Literal[4]`**, edited rather
> than defaulted, and **`PROTOCOL_VERSION` moves to 27** (§6).

**The loop stamps the link because the planner is the one component that must not.**
A model asked for a predecessor id would be asked to hand back a system identifier,
and ADR-0226 §9 already refused to put `ActionPlan.id` in a *log* on the ground that
*"`Identifier` admits any non-blank encodable string, so a `Planner` — or
`ModelBackedPlanner`'s own injectable id factory — may supply one carrying content"*.
Writing such a value into a durable audit chain is that hazard with the retention
lengthened. Nor is the link a decision the planner is in a position to take: it has
no opinion about which plan its output replaces, and it is not told which iteration
it is on (§12). The loop is the only component that knows, so the loop states it —
which is the same division ADR-0223 §2 draws when the engine computes the
externality value *"once, immediately after the turn is in hand"* and stamps it into
a `core` model the turn produced.

**Taking the field on every plan and not only on a revision is what closes the
forgery, and the gap is worth naming because the narrower rule looks sufficient.** If
the loop only *set* the field on a revision, a planner conforming by signature could
return its **first** plan already carrying a same-goal predecessor's id. Nothing
would revise, so nothing would overwrite it; `save_plan` would accept it, because the
reference resolves; and the store would hold a durable record claiming a supersession
that never happened — an unprovenanced identifier written into the audit chain, which
is the very thing the clause above refuses. Discarding rather than refusing follows
ADR-0226 §3's own posture for a model-invented label: the turn is not the place to
punish a planner's non-conformance, and the widest possible effect of the abuse is
that a field the planner does not own is ignored. It is not counted in §9's record
because, unlike a dropped label, it measures a planner's conformance rather than the
trigger's behaviour, and the shared `PlannerContract` (§12) is where conformance is
held.

**And the stamp is not an edit of a decision.** ADR-0014 §2's frozen rule exists so
that a plan is not mutated *"out from under an in-flight execution"*; the revision at
this moment has been persisted by nothing, driven by nothing and observed by nothing,
and every field the planner authored is byte-identical afterwards. §1's narrowed
prohibition is what keeps that from becoming a licence: `id`, `goal_id`, `steps`,
`rationale` and `read_request` are the planner's, `supersedes` is the loop's, and
there is no third case.

**What that costs is one turn's ask text, the cost is not new, and this ADR names
its enlargement rather than letting a reader discover it.** On a turn that fired,
whose servicing completed, and whose **second** planner call then raised, no plan is
persisted, so the ask the loop actually serviced is retained nowhere durable. Three
facts bound that, and the first is the one a reader is most likely to get wrong.
**ADR-0226 already ships turns of exactly this shape**: §11 item 10 requires a record
from *"a turn rejected for capacity, which `AssistantEngine` decides **after** the
loop has planned and serviced"* — fired, serviced, and persisting no plan — so §9's
sentence that *"The ask stays durable on the frozen `ActionPlan`"* was already the
ground for copying no text rather than a guarantee holding on every turn. **The live
instrument is §9's record and not the plan store**: §10's persisted-plan reading is
stated over *"the Lane-A-only window"*, before a servicer existed, and that window
closed when Lane B merged; the turn in question still emits its record, still carries
**fired**, still carries its servicing counts, and now says **planning failed**.
**And what is genuinely lost is a join ADR-0226 §12 has already deferred** — *"a join
from an audit event to the plan whose ask it describes"* — which §14 carries forward
with this population added to what fires it. The enlargement is a planner outage on a
second call, and the alternative was refused in the same breath as the last one:
carrying a plan out of a failing turn needs a second channel out of `respond` and a
second reason for the engine to write.

**Persisting every plan means every plan of a turn that persists one, and not a
retroactive write from a turn that failed.** ADR-0226 §10 already settles the
population: *"A turn whose planner did not return a plan persists none, so it is
absent from that population exactly as §8's not-reached turns are excluded from the
live one."* A turn whose **second** planner call raises is that turn one iteration
later — it produced a plan, it reached no `TurnResult`, and the engine's persistence
site is above the loop and never runs. Carrying the first plan out of a failing turn
so that it could be written would need a second channel out of `respond` and a second
reason for the engine to write, for a population the corpus has already excluded from
the persisted-plan figure and which §9's record — emitted from `respond`'s `finally`,
conditioned on nothing — already counts live. What this section requires is that a
turn which persists a plan persists **all** of them, which is the failure a design
persisting only the driven plan would have.

**Persisting every plan is not book-keeping; it is what keeps ADR-0226 §9 true.** That
section deliberately copies no text into the audit record, resting the retention on
one sentence: *"The ask stays durable on the frozen `ActionPlan` (§4) and the record
neither copies it nor points at it."* And §10 rests the Lane-A-window fire rate on the
same fact: *"every turn's plan is persisted through `PlanStore.save_plan`"*, so the
numerator and denominator are *"readable off the persisted plans"*. Under iteration the
ask that was actually **serviced** is on the *first* plan — which the turn then
replaces. A design that persisted only the plan it drove would silently delete the
record of why the turn read what it read, and would make ADR-0226 §9's minimisation
argument false the day this milestone ships. That is the reason, and it is a reason
about an existing ADR's integrity rather than a preference about audit richness.

**`supersedes` rather than an inference from `goal_id` and `created_at`, and the
contract is what decides it.** All of a turn's plans share a `goal_id` today, so a
reader could sort by `created_at` and call the later one the revision — but ADR-0014
§1 rules that *"a goal ('relocate to Lisbon in September') outlives any one
conversation"*, so a plan produced for the same goal on a **later turn** is
indistinguishable from a revision under that rule. `LearningLoop._goal_from` minting a
goal per turn is an implementation fact the contract contradicts, and an audit chain
resting on it would break silently the first time a goal is resumed. Recording the
link on the plan makes the chain a fact the store holds rather than one a reader
reconstructs — which is ADR-0227 §3's discipline, *"supplied, never inferred"*, applied
to the durable side.

**The store and the export checks are ADR-0014 §5's own promise kept, not a new
invariant**, and the distinction decides whether a record is owed. §5 already rules
that an export is *"complete and internally consistent: every `goal_id`/`plan_id`
referenced by an included record resolves within the same export"*, and ADR-0049 §1
states how that promise is kept at write time: *"`save_plan`'s app-level orphan check
(ADR-0014 §5 rejects a plan whose goal is unknown, so `export` can promise
referential integrity without repair)"*. A reader holding ADR-0014 §5 alone, adding a
`plan_id` reference to a record the export carries, is instructed by §5's own sentence
to make it resolve — identical conduct before and after, which is ADR-0070 §1's test
and the reason §15 records nothing against ADR-0014 §5. What this section supplies is
the *statement* that the new reference is inside that promise, so that the existing
validator's silence is not read as an exemption.

**A durable foreign key is deliberately not required, and ADR-0049 §1's own reason is
why.** Its `REFERENCES` constraints exist to close a *cross-process* window — *"one
connection deletes goal `g` between another's check and its insert"*. This reference
has no such window: both plans of a turn are written by that turn, oldest first, and
`PlanStore` offers no way to delete a single plan — `delete_goal` removes a goal's
plans together and both of a turn's plans share its `goal_id`, and `clear` removes
everything. So no interleaving leaves a live plan whose predecessor is gone. A
durable constraint is fired by a future member that deletes plans individually, or by
a chain that spans goals, which §1 forbids.

**Persisting the whole sequence before opening an execution is what keeps a partial
write from becoming a partial act.** The engine's order today is save the goal, save
the plan, open the execution, drive the step; the naive extension writes each plan as
it is produced, which would put a `save_plan` failure *after* a step had run. Nothing
here needs that order, the plans all exist by the time the loop returns, and the
failure a persistence error should produce is a turn that decided and recorded
nothing — not one that acted and then lost the record of why. §13's eighteenth test
asserts it at the engine rather than at the store.

**A superseded plan drives nothing, and the clause is stated because the tempting
implementation is a loop.** ADR-0226 §4 states the sibling rule for its own
addition — a `ReadAsk` *"is **not a `PlanStep`**, and nothing drives it"* — for the same
reason: a new object on the plan path attracts machinery. Here the object *is* a plan,
so the prohibition has to be explicit or the first implementation that iterates will
be tempted to drive each plan's first step as it goes. That is the plan-driving stage,
it is §14's, and it is not reached by accident.

### 6. The export version and the protocol version both move, and ADR-0226's statement about the second is corrected

> **Normative.** `PlanExport.schema_version` moves **3 → 4**, by the mechanism
> [ADR-0039](0039-what-a-finished-step-durably-records-about-why.md) §10 prescribes and
> ADR-0226 §4 last applied: the annotation is edited rather than defaulted, so a
> document of an earlier shape does not validate against this contract at all.

> **Normative.** **`PROTOCOL_VERSION` moves 26 → 27**, and `wire/envelope.py`'s log
> gains an entry naming this ADR and this reason. `ActionPlan` is carried to a client
> inside `TurnOutcome.turn.plan`; `wire/codec.py`'s projection dumps every field of a
> model; and `ActionPlan` sets `ConfigDict(extra="forbid", frozen=True)`. So a peer
> whose `ActionPlan` predates this field **fails to decode** every `TurnOutcome` a
> newer hub sends, on every turn rather than on a revising one.

> **Normative.** No lane reads this section as authority for bumping on a defaulted
> addition alone. What obliges the move is the **conjunction** — a wire-carried type,
> a projection that emits defaults, and `extra="forbid"` — and
> [ADR-0213](0213-a-record-carries-the-topics-it-is-about-proposed-once-at-write-and-never-inferred-at-read.md)
> §11's no-bump ruling for a defaulted addition stands for the case it decided, which
> `wire/envelope.py`'s log distinguishes in terms: *"Neither type sets
> `extra="forbid"`, so no decode fails in either direction."*

**This is the one place this ADR departs from ADR-0226's own words about the same
type, and the departure is a fact rather than a disagreement.** ADR-0226 §4 and §10
say *"`ActionPlan` crosses neither `wire/` nor `service/` in the tree"* and instruct
their lanes not to bump. Against `origin/main` the chain is
`wire/client.py`'s `converse` returning `TurnOutcome` → `TurnOutcome.turn:
TurnResult | None` → `TurnResult.plan: ActionPlan`, and `wire/envelope.py`'s own log
already reasons from the first two links for a different field: *"`TurnResult.memories`
is `tuple[MemoryRecord, ...]`, carried inside `TurnOutcome.turn`"*. ADR-0226 §10's
clause anticipated exactly this discovery — *"A lane that finds otherwise stops and
says so rather than bumping it"* — and this is the saying-so, one ADR later.

**What that leaves behind is a defect, and it is not this ADR's to repair.**
`ActionPlan.read_request` shipped at `PROTOCOL_VERSION` 26 without a move, so a client
built before it and a hub built after it both announce 26 and disagree about the
shape. Repairing it is a decision about a released version rather than about this
mechanism — it is filed as #1956, and a lane that takes it will find that the
move this section makes covers the shape going forward but says nothing about the
window already open. **This ADR neither repairs it nor inherits it.**

**And ADR-0226 §10's no-bump clause is not superseded**, because it is stated over its
own two lanes and those lanes have merged (§15). What it rests on is false; what it
required of them is done. §15 records the correction against ADR-0226's header so a
reader implementing from that ADR meets it.

### 7. The supply under iteration: monotone, one fourth group, one budget per servicing

> **Normative.** The supply is **monotone across a turn's iterations**. The three
> groups the first call saw keep their contents, their order and their positions; the
> fourth group only grows; and nothing is removed from the supply between the first
> planner call and the last. No implementation subtracts, re-filters, re-ranks or
> re-orders the supply on account of a revision.

> **Normative.** The records **every** servicing of a turn returns form **one fourth
> group**, appended whole after the episodic supplement in servicing order — the
> first servicing's records, then the second's. There is no fifth group, and
> ADR-0226 §7's append-never-interleave rule and ADR-0158 §4's positional argument
> bind over the whole of it.

> **Normative.** **Each servicing draws its own budget of ten** (ADR-0226 §6),
> counted after deduplication **against the supply as it stands when that servicing
> runs** — which on the second servicing includes the first's yield. ADR-0226 §6's
> cross-kind precedence, its two-label cap and its second-budget rule bind per
> servicing, unchanged. A turn's fourth group therefore holds at most twenty records.

> **Normative.** ADR-0226 §7's deduplication ranges over the **whole union**, the
> earlier servicing's yield included. A record the second servicing reaches that the
> first already added enters the group once, at its first arrival's position, and
> consumes no slot of the second budget.

> **Normative.** ADR-0204 §2's withholding evaluation, as ADR-0226 §7 moved it, is
> taken **once, after the last servicing the turn performs**, over the turn's final
> supply. ADR-0223 §2's externality value is computed once over that same final
> supply, exactly where it is computed today. Neither is computed twice, and neither
> is computed from a supply an earlier iteration held.

> **Normative.** The `TurnResult` is constructed **once**, over the final
> deduplicated union, after the last iteration. ADR-0226 §7's clause binds unchanged:
> no implementation constructs one and then edits it, and none exists in an
> intermediate state another stage can observe.

**Monotonicity is the safety property this whole design rests on, and it is worth
naming as one rather than leaving it as a description.** ADR-0223's own docstring for
`SelectionOrigin.over` names the failure it forecloses: *"plan a step over tainted
material, re-plan over clean material, stamp the binding from the last selection, and
watch the fact clear … A warrant is never un-received, and neither is a selection."*
That is a description of re-planning done wrong, written before any re-planning
existed. Under this section it cannot happen: nothing leaves the supply, so the union
the last iteration holds is a superset of every earlier one, and a stamp or an
evaluation taken over the final supply covers everything any iteration saw. §11 takes
the same property for the steered-loop question.

**One fourth group and not one per servicing**, because ADR-0158 §4's argument is
positional — *"Position is how this corpus expresses precedence into a prompt"* — and a
fifth group would be a new position in the prompt encoding for a distinction the
consumer cannot act on. It also keeps ADR-0226 §7's own text literally true and
keeps `planning/planner.py`'s leading-`EPISODIC`-run split untouched: a group appended
at the tail cannot extend that run, however many servicings filled it.

**A budget per servicing rather than one shared across the turn, and the alternative
is worse in the case that recurs.** ADR-0226 §6 gives the emission ten records and
notes that a sighted query *"can return the whole budget on *every* firing"*. Under a
turn-wide budget the second servicing would ordinarily receive nothing, which makes
the second emission an instrument reading with no read under it — the shape ADR-0226
§11 item 11 calls out for the empty request. Two budgets cost prompt size, which is
the honest cost: at most twenty serviced records beside a belief budget and an
episodic supplement of thirty (ADR-0224 §1). §9 is where that cost is watched.

**And the evaluation moves by one word rather than by a new rule.** ADR-0226 §7
already took ADR-0204 §2's evaluation *"once, over the turn's **final** supply"*; what
"final" means is what iteration changes, and §15 records the phrase rather than the
clause.

### 8. The label space is the sequence passed on that call, and the second level is reached only through a fresh judgement

> **Normative.** ADR-0226 §3's labelling binds each planner call **separately and as
> written**: the label of the record at 1-based index *n* of the `memories` sequence
> passed on **that call** is `M` followed by *n*. The loop resolves a label by
> indexing *"the very sequence it passed on this call"* and never a sequence from an
> earlier call. The same label string may name different records on a turn's two
> calls, and that is the scheme working rather than a collision to repair.

> **Normative.** **Within one servicing, a citation hop follows exactly one level.**
> ADR-0226 §3's clause — a hop follows *"**only** the labelled record's own stored
> `Provenance.evidence`"* — binds each servicing entire, and no servicer follows the
> evidence of a record it reached in the same servicing.

> **Normative.** **A second level is reachable across iterations, and only because
> the planner named it.** A record the first servicing's hop fetched stands in the
> supply, is labelled on the second call, and its own `Provenance.evidence` is
> reachable by a `CITATION_HOP` the second plan emits. No implementation reaches it
> any other way: not by depth, not by a transitive resolver, not by following
> evidence the model did not name.

> **Normative.** ADR-0226 §3's namer rule binds every call of every turn: **no record
> identifier is rendered to a model and none is accepted from one**, no label survives
> the call that rendered it, and no label is persisted as a reference.

**This is the clause ADR-0226 §3 reserved, and taking it is what makes the depth safe
rather than merely available.** That section ends *"no lane adds a second level: that
is iteration, and it is §12's"*, and the reason it gives for the whole scheme is that
the label discipline *"forecloses"* a model steering what it is shown, because *"the
resolvable set is exactly what the loop chose to render, so the widest possible abuse
of the mechanism is asking for something already on screen"*. Iteration preserves that
exactly. The second level is not a deeper traversal the resolver performs; it is a
record the loop **chose to render**, labelled, that a model then asked for. Every
property §3 bought is intact — the namer is still the model pointing at data the loop
selected, the identifier still never crosses the seam, and an invented label is still
an index outside the range.

**Depth by judgement rather than depth by parameter is also the better mechanism on
the evidence.** The replay's oracle shape is *"311/349 need **exactly one** belief, 29
need two, 9 need three"*: a mechanical second level would spend the budget on the 8%
case for every question, where a judged one spends it where a model that has seen the
first level's yield thinks it will pay. #1844's own framing of the risk — the namer
rule — is a rule about *who points*, and this keeps the pointer with the party the
rule names.

### 9. The trigger, the fire rate and the audit under iteration

> **Normative.** The trigger is unchanged and is still the emission (ADR-0226 §8). A
> turn's trigger **fired** if **any** plan that turn produced carried a
> `read_request`; it **did not fire** if the turn produced at least one plan and none
> carried one; and it was **not reached** if the turn produced no plan at all.

> **Normative.** **The fire rate stays a per-turn rate and keeps its meaning.** Its
> numerator is turns whose trigger fired by the clause above and its denominator is
> turns on which the trigger was reached, so the live figure remains directly
> comparable to the replay's 13.6% and to milestone 27's own. **No lane divides
> emissions by turns and calls the result a fire rate**, and no lane reports a figure
> over emissions without saying that is what it is.

> **Normative.** ADR-0226 §9's record is **extended and not replaced**, which is what
> §9 itself provides for: *"These are the fields milestone 2 **raises rather than
> replaces**. An ADR admitting a second serviced emission per turn extends this record
> to account per emission and keeps every field's meaning."* One record, one turn, one
> event key, one `INFO` line, emitted once and conditioned on nothing — every clause of
> §9 binds unchanged.

> **Normative.** The record's per-servicing counts — kinds, records returned, records
> new after deduplication, records deduplicated out, labels resolving to nothing,
> whether the budget truncated a kind, whether the servicing failed, and whether a
> read it had already performed had returned records when it did — become an
> **ordered sequence, one entry per servicing**, in servicing order. Every field keeps
> the meaning §9 gives it, over its own servicing. The record gains two turn-level
> fields: **how many planner calls the turn made**, and **why the turn stopped
> iterating**.

> **Normative.** "Why the turn stopped" is a closed vocabulary of **five**: **not
> iterated** (no revision was admissible — §2's conditions (a) to (e)), **settled**
> (the last plan carried no request), **bound reached** (§3), **budget reached**
> (§4), and **planning failed** (a planner call after the first raised, or the turn
> ended between a servicing and the next plan's return). No implementation, setting
> or later lane adds a sixth without the ADR that decides it.

> **Normative.** **"Not iterated" is the record's default**, so a turn that ended
> before it reached a first plan carries it and says something true — it did not
> iterate. What separates that turn from one that reached a plan and found no
> revision admissible is §8's `trigger` outcome, **not reached** against **fired** or
> **not fired**, which is the same division ADR-0226 §9 already draws between its
> `trigger` and its `servicing` defaults. No lane reads "not iterated" as a claim
> that a first plan existed.

> **Normative.** ADR-0226 §9's **counts-and-kinds rule binds the extension entire**.
> The record still copies no text — no query, no label, no `content` span, no excerpt,
> no rendering — carries **no plan identifier** and no identifier but the ambient
> correlation id, and carries no timing figure that would let a query's latency be
> attributed to a record.

> **Normative.** The **iteration rate** — the share of fired turns that revised — and
> the **stop distribution** are new figures this record supports. Neither is a
> precision or a recall, neither is a novelty rate, and ADR-0226 §8's prohibition on
> reporting precision or recall from this record alone binds them too.

**Keeping the fire rate a per-turn rate is the point of stating it, because the
tempting definition breaks the one number ADR-0226 says is comparable.** That section
fixes the live fire rate against the replay's 13.6% and calls it *"available on day one
and needs no label at all"*. A turn that emits twice is one turn; counting emissions
over turns would produce a figure above 100% in the limit and would move for a reason
that has nothing to do with the planner's judgement about a first supply. The
per-turn definition also survives the bound moving, which is what a comparable series
needs.

**The fifth member exists because a turn can fail between its two plans, and the
record still has to say something true.** ADR-0226 §9 emits *"once per turn"*,
*"conditioned on nothing"*, so a second planner call that raises still writes a
record — and none of the four successful outcomes describes it. Labelling such a turn
**settled** would say the planner stopped asking when it did not; **bound reached**
would say a guard fired when none did. A vocabulary that forces an implementation to
pick a falsehood is a vocabulary with a hole, and §13's fifteenth test asserts this
arm rather than leaving it to be discovered. It is a stop *reason* and never a turn
outcome: the original failure still propagates unchanged, exactly as ADR-0226 §11
item 10 requires of its own arms.

**Two turn-level fields and a sequence, rather than a second event.** §9 forbids a
second audit beside this one in terms, and the shape it prescribes — *"account per
emission"* — is a sequence. Putting the stop reason at the turn level rather than in
the last entry is what makes the guard rates readable without reconstructing them:
*"how often does the budget fire"* is a count over one field.

**The stop distribution is where §4's judged figure becomes a measurement.** If the
budget fires on a large share of turns, twenty seconds is wrong for the surface; if it
never fires, the count is the only guard and the budget is inert. Neither is knowable
before deployment, which is why the guard exists **and** is instrumented, exactly as
ADR-0226 §8 made the trigger's own rate an instrument rather than a claim.

### 10. The stop is told to the composing stage, and that is what "degrades legibly" means

> **Normative.** On a turn that stopped at the **bound** (§3) or at the **budget**
> (§4) with its last plan still carrying a `read_request`, the composing stage is
> given the bare fact that **the turn stopped looking while it was still asking**, and
> composes an answer that says so. On every other turn it is given nothing, and the
> assembled prompt is byte-identical to what it is today.

> **Normative.** The fact carries **no count, no duration, no guard name, no query and
> no label**. It does not say which guard fired, how many times the turn looked, or
> how long it spent. ADR-0226 §9's counts-and-no-copy reasoning binds this carrier for
> the same reason it binds the audit: nothing bounds what a planner puts in a query,
> and the turn's timing is a fact about the system rather than about the user's
> question.

> **Normative.** This fact is carried **inside `ai_assistant.orchestration`**, from
> the component that knows it to the render site, as data. It adds **no field to a
> `core` type**, no member to a Protocol, and it is never inferred at the render site
> — not from the plan, not from the supply's length, not from the audit. This is
> ADR-0227 §3's rule, applied to a second fact for its own reason.

> **Normative.** No lane renders this fact through the step account. ADR-0170 §5a's
> closed vocabularies are unchanged and gain no member, and the step account
> continues to describe the step.

**"Degrades legibly" is a claim about the reply and it needs a fact to rest on,
because nothing else about the turn looks degraded.** A turn that hits the bound has a
plan, a supply wider than the one that plan was made over, and an answer composed from
all of it. The user's experience is a good answer; what is missing is invisible. The
only honest degradation signal is the one the system actually holds: **its planner was
still asking when it stopped**. Telling the composer that, and nothing else, is the
same construction ADR-0203 uses for a withholding — the stage is told *that* something
happened *"so it can compose an answer that states it"* — rather than a filter or a
rendered apology.

**One fact and not two, because the user cannot act on the difference.** A reply that
named the deadline would invite a retry, and a retry hits the same bound over the same
supply; a reply that named the count would be telling the user about the system's
budget. Which guard fired is an operator's question and §9 answers it.

**And byte-identical on every other turn is stated so that it is testable.** ADR-0227
§3 makes the same guarantee for its own carrier — *"An empty set renders no reply line
anywhere, and the assembled prompt is then byte-identical to what it is today"* — and
it is the clause that keeps a new prompt input from silently moving every reply the
system composes.

### 11. Inward only, and why iteration does not open the steered loop

> **Normative.** This ADR adds **no kind** to ADR-0226 §2's enumeration. Both kinds a
> revision may emit are the two that ADR admits, both terminate in the owner's own
> `MemoryStore`, and no lane admits an outward kind here or reads this ADR as
> preparing for one.

> **Normative.** A revision's request is **composed over records the second call was
> shown**, which may include records carrying the external mark. That is admitted and
> not prevented: no lane filters the fourth group, subtracts an externally-derived
> record from a supply, or narrows what the second call sees on the strength of a
> record's origin. ADR-0204 §4's narrowing prohibition and ADR-0226 §7's
> discards-nothing-by-class clause bind here unchanged.

> **Normative.** A planner-composed query is a **model completion with no recorded
> origin**, of the same class as `ActionPlan.rationale`, at **every** iteration
> (ADR-0226 §9). A query composed over a wider supply is not of a better class than
> one composed over a narrower one, and no lane infers a placement for it, renders it
> to a channel a rationale is inadmissible to, or treats it as evidence of anything.

> **Normative.** ADR-0223's externality value and ADR-0204 §2's withholding value are
> computed over the turn's **final** supply (§7), so a record that entered at any
> iteration is inside both. **No lane recomputes either from an intermediate supply**,
> and no implementation clears, narrows or re-derives a stamp because a later plan was
> made over different material.

**#1844's one genuinely new risk is named and it is not opened here.** The note is
precise about the shape: *"iteration one reads attacker-controlled content; iteration
two decides what to fetch **based on it**… That is an exfiltration channel needing no
write capability at all"*, and its sequencing consequence is *"A steered loop that can
only read the owner's own disk has no channel out."* This ADR's loop can only read the
owner's own **store**, which is the rung below even that. A `SIGHTED_QUERY` becomes an
`assemble_by_band` call over a local store and a `CITATION_HOP` becomes an index into a
sequence the loop itself passed: no byte of a model-composed request leaves the
process on either path. The steering is real — iteration two's ask **is** composed over
iteration one's yield, and this ADR says so rather than denying it — and it is
contained by there being nowhere for it to steer *to*.

**What steering can still reach is an act, and the corpus already governs that.** A
revised plan may name a step, and that step may reach the egress seam. ADR-0223 §6
rules that a binding carries `planned_with_external_content` where a stamped episode
was in the turn's supply, *"exactly as it applies for any other reason"*, and that no
lane adds a carve-out. Under §7's monotonicity a record that entered at the first
servicing is still in the final supply, so a turn whose revision was composed over
external material stamps its binding and its capture — and the product sentence
ADR-0223 §6 states, *"every subsequent turn of that conversation that reaches the
egress seam is a confirmation rather than an allow"*, applies to a revised turn
verbatim. This ADR relaxes nothing there and cites it toward no designation.

**The class clause is the one an implementer will be tempted to soften.** A query the
planner composed after seeing the hop's yield *feels* better grounded than a blind
one, and ADR-0226 §9's reason for classing it says why the feeling is not a fact: it
is a model completion, *"a model completion is unplaceable"* (ADR-0203 §1), and
nothing bounds what a model puts in one. Iteration changes what the model read, not
what the model's output is.

### 12. What the implementing lane owes

> **Normative.** **One lane**, briefed from this ADR's merged text, and not before
> milestone 27's exit is ruled.

> **Normative.** In `core/types.py`: `ActionPlan.supersedes` with its default,
> `PlanExport.schema_version` at `Literal[4]`, and the widened docstrings on
> `ActionPlan` and `PlanExport`. In `wire/envelope.py`: `PROTOCOL_VERSION` at 27 with
> its log entry (§6). In `orchestration/`: the revision loop in `LearningLoop` with
> §2's seven conditions, §3's bound, §4's budget read from the operation and checked
> against the injected clock, §7's single fourth group and per-servicing budgets,
> §9's raised audit, §10's carrier to the composing stage, and the persistence of
> every plan at the engine's existing site.

> **Normative.** In `planning/`'s **planner**: nothing. `planning/planner.py`'s
> prompt, its emission and its parser are unchanged, and **the planner is not told
> which iteration it is on**. No lane adds an iteration index, a "last look"
> instruction or any other signal to the planner's input, and `Planner.plan`'s
> signature gains no parameter.

> **Normative.** In `planning/`'s **stores**: §5's rejection, and nothing else.
> `planning/store.py` and `planning/sqlite_store.py` each refuse a `supersedes` that
> does not resolve, names the saving plan's own `id`, or names a plan under a
> different `goal_id`. Nothing else about either store moves — no member, no schema
> column, no foreign key (§5), no change to the goal check, the id-reuse check or the
> stored-copy rule.

> **Normative.** In `core/protocols.py`: the lane **widens `Planner.plan`'s
> documented meaning in exactly two respects and no others** — that `memories` may
> carry the fourth group on a turn's **second** call, and that a turn may put two
> requests to one planner, replacing that docstring's *"never a second request on the
> same turn"*. It **also** widens `PlanStore.save_plan`'s documented rejection set by
> §5's one clause. Both are **flagged as breaking changes under golden rule 5**, and
> the two compatibility facts are stated separately because they differ. The
> `Planner` widening breaks nothing: no signature moves, `supersedes` is additive and
> defaulted, and every existing implementation conforms exactly as it does today. The
> `PlanStore` widening is **source-compatible and behaviourally breaking**: a store
> that accepts a `supersedes` naming a plan it does not hold stops conforming the
> moment §5 binds, which is why the clause below obliges both implementations and
> their shared suite rather than the documentation alone.

> **Normative.** The lane **extends the shared `PlannerContract` conformance suite**
> (`tests/planning/planner_contract.py`) for the widened input, so that every
> `Planner` implementation is held to it through the `Test…Contract` subclasses that
> already run it — a planner handed four groups plans over them and emits under the
> same rules. This is the obligation ADR-0226 §10 put on its own lane for its own
> widening, taken here for the same reason.

> **Normative.** The lane **also extends the shared `PlanStore` conformance suite**
> (`tests/planning/plan_store_contract.py`) with §5's three rejection arms, and
> **updates both implementations** — `planning/store.py`'s in-memory store and
> `planning/sqlite_store.py`'s durable one — to satisfy them. That widening is
> behavioural, not merely documented: a store that accepts an unresolvable
> `supersedes` stops conforming the moment §5 binds, and a suite left unextended
> would leave the rejection asserted by nothing. §13's eleventh test is that
> obligation stated as behaviour.

> **Normative.** The lane **adds no Protocol, no member to one and no parameter to
> any signature**. Where it finds a change of that kind owed, it stops and says so
> rather than making one.

> **Normative.** The lane implements, prepares for, and leaves a hook for **none** of
> §14's deferrals, and in particular does not drive a second `PlanStep`, admit an
> outward kind, or admit an archive entry to a prompt, to the supply or to a citation
> resolution (ADR-0225 §12).

> **Normative.** A hub and its clients are **redeployed together** on this lane's
> merge, because `PROTOCOL_VERSION` moves.

**One lane, under [ADR-0137](0137-the-contract-seam-is-where-a-slice-is-cut.md)
§1's own test.** That test is where *substantial new machinery* lands: *"A slice is one
lane only if its implementation puts substantial new machinery into at most one
subsystem."* Every piece of machinery here is in `orchestration` — a loop, seven
conditions, a clock check, a carrier and a raised audit. `core/types.py` gains one
defaulted field and one edited annotation, and `wire/envelope.py` gains an integer and
a comment; ADR-0226 §10 already ruled that shape, saying of its own additions that
*"The types Lane A adds are `core/types.py` models with validators, which the ordinary
rule covers."* This is the same rule with less in it.

**The Protocol widening does not make this two lanes, and the test is where machinery
lands.** ADR-0137 §1 asks where *substantial new machinery* goes, and a docstring is
not machinery. What the lane touches in `planning`'s tree is
`tests/planning/planner_contract.py`, the shared conformance suite — the guardrail for
a widened meaning rather than an implementation of one — and `planning/`'s production
code is untouched. ADR-0226 §10 drew exactly this line for its own widening, binding
its Lane A to the suite while noting that *"this ADR adds no Protocol, so no triad
exists to split and §3 has no subject here"*; the same holds here.

**Which is why this ADR's implementation is one lane where ADR-0226's was two**, and
the difference is worth stating so it does not read as a shortcut. ADR-0226 split
because its Lane A put a labelled rendering and a second parser into `planning` — real
machinery in a second subsystem. This ADR puts nothing there at all, and §2's
conditions are the reason: every one of them is a fact the **loop** holds.

**Not telling the planner which iteration it is on is a decision, not an omission.**
ADR-0226 §8 rules that *"No lane makes the trigger's firing conditional on a setting, a
channel, a surface or a deployment flag"*, and a prompt that said *"this is your last
look"* would make the second emission a function of the bound rather than of the
supply — measurable, and measuring something other than the planner. Keeping the
prompt identical also keeps the two emissions of a turn comparable to each other and
to milestone 27's single one, which is what §9's iteration rate needs to mean
anything. The cost is that a planner at the bound may ask for a read whose yield
reaches only the reply, and §3 accepts it: that yield is milestone 27's whole
mechanism and it is not a loss.

**Waiting for milestone 27's exit ruling is what #1952 requires and what #1929 and
#1944 make sensible.** Both probes failed the milestone's headline clause, one at the
trigger and one at the render; a revision built on a trigger that does not fire and a
yield that does not render would inherit both. The ADR can merge now because it
decides the shape; the implementation cannot start until the shape below it is known
to work.

### 13. The representative-input tests this decision owes

> **Normative.** The implementing lane owes tests for each of the following, and each
> is a test over behaviour rather than over a call count.

1. **A step's parameters are filled from what the read returned.** A turn whose act
   needs a value only memory holds: the first plan cannot name it and emits a request;
   the servicing returns the record; the **second** plan's step carries the value in
   its parameters; and that step is the one the engine drives. Asserted over the driven
   step and over the persisted plans. This is the milestone's exit shape on the reading
   this ADR takes (§15), and it is the one test that fails if revision is merely wired.
2. **The bound is reached and the reply says so.** A planner that emits a request on
   every call: exactly two planner calls, both emissions serviced, the second plan
   driven, the audit recording **bound reached**, and the composing stage given §10's
   fact — asserted through the **production renderer** over the assembled prompt, per
   ADR-0227 §7's fidelity rule, and not through a fake that cannot fail to carry it.
3. **The budget is reached and the reply says so.** An injected clock whose reading
   passes the operation's budget between the first planner call and §2's check: one
   planner call, the first plan driven, **budget reached** in the audit, §10's fact in
   the prompt. Three further arms, each deterministic on an injected clock: an elapsed
   reading **exactly equal** to the budget stops the turn and records **budget
   reached**, an elapsed reading one tick **below** it admits the second call, and a
   turn whose planner call **overruns** the budget while in flight is not abandoned —
   which is §4's stated cost asserted rather than assumed. And one arm pins the
   budget's **origin**: a turn whose work *before* the first plan — context assembly,
   the two relevance reads, the first planner call itself — already consumes the
   budget starts **no** second call, which is the assertion an implementation timing
   from the first plan's return would fail while satisfying every arm above.
4. **A servicing that adds nothing does not revise.** Every returned record already in
   the supply: exactly one planner call, no second store read, **not iterated** in the
   audit, and the supply byte-for-byte what one servicing left.
5. **A failed and a partial servicing do not revise.** ADR-0226 §5's three arms
   (the first store call raising; a hop returning and the query then raising; a later
   band raising after an earlier returned): in each, one planner call, the supply
   byte-for-byte the three groups planning saw, and the audit carrying §9's failure
   pair with **not iterated**.
6. **An operation that declares no budget does not iterate**, asserted for a
   bounded-audience operation that declares none — so the arm is about the declaration
   and not about the audience — and for `converse_spoken`, whose servicing ADR-0226 §5
   declines and which therefore fails §2(c) as well.
7. **The label space is the sequence passed on that call.** The same label string
   resolves to different records on a turn's two calls; a label naming a record the
   **first servicing added** resolves on the second call and resolved to something else
   or to nothing on the first; and no model-supplied string reaches `get_many` as an
   identifier on either call.
8. **The second level needs a fresh emission.** Within one servicing, a hop whose
   fetched record itself cites further evidence adds only the first level; on the next
   call, a plan naming that record's label reaches the second level. Asserted over the
   fourth group's contents on each servicing.
9. **Every plan is persisted and the chain is legible.** A revising turn persists two
   plans under one `goal_id`; the second's `supersedes` is the first's `id`; the first
   still carries the `read_request` that was serviced; the export carries both at
   `schema_version` 4; and a document labelled 3 does not validate as a `PlanExport` at
   all.
10. **The loop sets `supersedes` and the planner sets nothing.** Four arms. The
    revision the turn persists differs from the plan the planner returned in
    `supersedes` and in **no other field**, asserted field by field against the
    planner's own return value. A planner that returns its **revision** already
    carrying some other plan's id persists the loop's value, not that one. A planner
    that returns its **first** plan carrying a resolvable same-goal id — the spoof a
    rule stated only over revisions would let through — persists `None`, and the turn
    is otherwise unaffected: nothing raises, nothing parks, and §9's record carries no
    count of it. And no plan identifier appears in any prompt the turn assembles,
    asserted through the production renderer.
11. **A `supersedes` that does not resolve is refused, at the store and in the
    document.** `save_plan` rejects a plan whose `supersedes` names a plan the store
    does not hold, one naming the saving plan's own `id`, and one naming a plan under a
    different `goal_id` — three arms, each a `PlanningError`, on **both** conforming
    `PlanStore` implementations through the shared conformance suite. And a
    `PlanExport` carrying a plan whose `supersedes` names a plan the document does not
    carry does not validate, beside the existing dangling-`goal_id` arm.
12. **The superseded plan drives nothing.** It starts no execution, reaches no
    `StepRunner`, no gate and no executor; exactly one capacity slot is taken by the
    turn; and a superseded plan whose first step names a side-effecting capability
    still runs nothing.
13. **The evaluation and the stamp are taken once over the final supply.** On a turn
    with two servicings, a record ADR-0199 §3 withholds that arrives in the **first**
    servicing sets the value the capture records, and so does one carrying the mark
    ADR-0217 moved into `MemoryBase.placement`; the externality value is computed once
    and is the same boolean the egress binding carries. This fails on any
    implementation that evaluates between iterations.
14. **The supply is monotone and the fourth group is one group.** The three groups the
    first call saw are byte-identical in the `TurnResult`; both servicings' records
    follow them in servicing order as one appended run; a record both servicings reach
    appears once, at its first arrival's position, consuming no slot of the second
    budget; and `planning/planner.py`'s leading-`EPISODIC`-run split is unaffected.
    And ADR-0227 §3's hop-set carrier **accumulates across both servicings** rather
    than the second replacing the first: a record the **first** hop reached still
    renders its reply in the prompt the turn finally assembles, asserted through the
    production renderer under ADR-0227 §7's fidelity rule.
15. **The audit accounts per emission and the fire rate keeps its meaning.** One record
    per turn carrying two servicing entries, the turn-level trigger **fired**, two
    planner calls, and the stop reason; a turn whose **second** planner call raises
    emits exactly one record still saying **fired**, with **planning failed** as its
    stop reason, the original failure propagating unchanged and **no plan
    persisted** — the engine's persistence site is above the loop and never runs,
    which is the turn a design carrying a plan out of a failure would have written; a
    turn that ended before any plan emits one saying **not reached** with the default
    **not iterated**; and a turn whose first plan carried a request and whose revision
    carried none is **fired**, not **not fired**.
16. **The audit still copies nothing.** Neither a distinctive span of a returned record
    nor either iteration's query string appears anywhere in the record; no plan
    identifier appears, including the superseded plan's; and the correlation id is the
    only identifier on the event.
17. **On a turn that did not revise, nothing moved.** The prompt the composing stage
    assembles is byte-identical to today's, the audit's per-servicing sequence has at
    most one entry, `ActionPlan.supersedes` is `None`, and the `TurnResult` is
    constructed once.

18. **A `save_plan` that raises mid-sequence loses the turn and not an act.** At the
    engine, on a revising turn whose **first** `save_plan` succeeds and whose
    **second** raises: the error propagates, the store holds the predecessor and no
    successor, no execution was opened, no step-execution capacity slot was spent, no
    step ran, and §9's record was emitted exactly once. Asserted at the engine and
    not at the store, because what it is about is the **order** of persistence
    against driving — an implementation that wrote each plan as it was produced and
    drove between them would pass §13's eleventh test and fail this one.
### 14. Deferred, by name, each with what fires it

- **The plan-driving stage, and with it a revision that follows a *driven* step's
  output.** ADR-0037 named it — *"Step ordering, dependencies (`UNMET_DEPENDENCY` has
  no producer yet), cancellation and the loop over `ActionPlan.steps` are the next
  slice"* — and ADR-0042 §3 attached an overall decrementing per-request deadline to
  it. It additionally needs a rule for parking mid-plan (#257 is open on a ruling
  outliving its transition) and for an `INDETERMINATE` step in the middle of a plan
  (ADR-0014 §4). Fired by its own ADR, on `track:planning` or beside it. **Not fired
  by a lane finding a two-step plan drives only its first step**, which is the system
  as ratified.
- **Decomposition — several asks of one kind in one emission** (ADR-0226 §2's
  at-most-one-of-each rule, ADR-0226 §12). Iteration already gives the planner a
  second ask of each kind, and gives it **with sight of the first ask's yield**, which
  is strictly more informed than two blind asks in one envelope; and admitting *n*
  asks would reopen ADR-0226 §6's budget split and cross-kind precedence, which is a
  second decision. Fired by §9's audit showing that a turn's two queries are
  ordinarily different facets of one compound question rather than a follow-up on the
  first's yield. Not fired by a lane finding one ask per kind restrictive.
- **A third planner call, and a configurable bound or budget.** §3 and §4 fix both
  figures. Fired by the ADR that moves them, on evidence from §9's stop distribution
  and iteration rate. Not fired by a deployment wanting more reach.
- **A cancelling deadline** — one that abandons a planner call in flight rather than
  declining to start one (§4). It needs a cancellation posture for a model call the
  turn has already paid for, and a rule for what a half-composed plan is. Fired by
  §9's record showing turns whose overrun is large enough to matter.
- **A revision on an unbounded-audience operation.** ADR-0226 §5 declines the
  servicing there and §2(c) inherits that; ADR-0203 §2's backfill clause is why.
  Fired by whatever fires ADR-0226 §12's own entry for that channel, and by nothing a
  lane notices about a thin spoken reply.
- **#1695's store step.** A stated fact makes the planner plan a store step no tool
  can carry, and the reply says the system cannot remember. **Revision does not absorb
  it**, and saying so is the point of the entry: nothing about that turn is
  information-insufficient — a second read returns more records and the planner still
  plans a store step, because the defect is that it does not know intake is the
  observer's (ADR-0093). It is a capability-vocabulary and composing question
  (ADR-0211, ADR-0176) on `track:conversation`. Fired there, and not by this track.
- **#838's coverage layer and its interactive-versus-proactive spend profiles.** #838
  puts sufficiency at *"the consumer (model judgment)"* and coverage as a *"mechanical
  estimate from store aggregates"*, and observes that *"proactive (assistant-initiated)
  retrieval has neither backstop nor deadline"*. §4's budget is an interactive figure
  on an interactive surface; a proactive spend profile needs a proactive turn path,
  which this loop is not. Fired by #838's own ADR.
- **The ask text of a turn that fired, serviced and then failed before the engine's
  persistence site** (§5). ADR-0226 §12 already defers *"a durable, queryable surface
  for §9's audit, and with it a join from an audit event to the plan whose ask it
  describes"*, and notes that the join needs *"trustworthy provenance at the seam"*
  because an `Identifier` carries none. This ADR enlarges that population by one
  shape — a second planner call that raised — and adds nothing else to the deferral.
  Fired by that surface's own ADR. **Not** fired by a lane wanting to carry a plan
  out of a failing turn, which §5 refuses.
- **Repairing `PROTOCOL_VERSION` for `ActionPlan.read_request`** (§6). Filed as
  #1956. Fired there, and not by this ADR's implementing lane, which moves the
  version for its own field and inherits nothing about the window already open.

### 15. Scope, and what this records against earlier ADRs

**This ADR partially supersedes five ratified ADRs, in eight scopes, and no others**
— **five** of ADR-0226, one each of ADR-0158, ADR-0014 and ADR-0204. ADR-0226's five
are §2's second-emission clause, §3's second-level clause, §6's one-emission clause,
§7 (its re-planning prohibition, its evaluation-timing phrase and its three-group
restatement, taken as **one** scope because all three are §7's and all three move for
the one reason a turn now plans twice), and §8's trigger clause. That is a
classification of this change and is therefore stated as prose rather than marked
(ADR-0089 §1); what follows is the working under ADR-0070 §1's test, and for the
clauses a reader would most expect to have moved with them and which did not.

**ADR-0226 §2's second-emission clause is partially superseded, and it is the clause
`core/protocols.py` carries.** §2 rules that *"One emission may carry **at most one
ask of each kind**, and is serviced **once**"*, and then that *"nor is a second
emission on the same turn, which is re-planning and is §12's"*. ADR-0228 §3 admits a
second emission. The `Planner` Protocol's own docstring states it as *"It emits **at
most one ask of each kind**, and never a second request on the same turn — that is
re-planning, which ADR-0226 §12 defers"*, so a reader holding only ADR-0226 builds a
planner that refuses to emit twice and an orchestration that would not service it.
ADR-0070 §1's test is met. **The scope is the second-emission sentence alone**: the
at-most-one-ask-of-each-kind rule binds **per emission**, unchanged; two asks of one
kind is still not an emission this corpus admits (§14 defers decomposition); and §2's
two kinds, their servicing and the argument for shipping them together are untouched.

**ADR-0226 §6's one-emission clause is partially superseded, and §6 names the ADR that
may do it.** §6 rules *"One emission is serviced **once** per turn"* and that *"no
configuration, setting or later lane makes the count configurable without the ADR that
decides it (§12)"*. This is that ADR. A reader holding only ADR-0226 services one
emission and stops; after this ADR, on a turn meeting §2's conditions, they service
two. ADR-0070 §1's test is met and §3's partial form is the tool. **The scope is the
count and nothing else of §6**: the budget of ten, the hop-first precedence, the
two-label cap, the second-budget rule and ADR-0113 §5's inherited non-promise all bind
**per servicing**, unchanged.

**ADR-0226 §7's re-planning prohibition is partially superseded, and it is the
clearest of the seven.** §7 rules that *"no lane closes the gap by re-calling the
planner: §6 services one emission once and ADR-0014 §2's frozen plan stands (§12)"*.
This ADR re-calls the planner. The clause names §12 as where the question goes and §12
names this milestone, so the deferral and the prohibition are discharged and superseded
in that order — the pattern ADR-0226 §13 itself set for ADR-0208 §8, where *"A deferral
of the *decision* and a normative clause that forecloses it in the meantime are both
real"*. **The scope is that sentence.** §7's fourth-group construction, its append rule,
its whole-union deduplication, its discards-nothing-by-class clause and its
constructed-once clause bind unchanged and are relied on by §7 here.

**ADR-0226 §7's evaluation-timing phrase is partially superseded by one word.** §7
takes ADR-0204 §2's evaluation *"once, over the turn's final supply … after
servicing"*. On a turn with two servicings a reader holding only ADR-0226 may take it
after the first, and would then record a value about a supply the turn did not compose
over — the same failure §7 moved the clause to prevent, one iteration later. §7's
*"once"*, its set, its terms and the field it writes are untouched; what moves is which
servicing "after servicing" names. ADR-0204 §2 itself is **not** reached again: its
timing clause is already ADR-0226's scope, and this ADR moves ADR-0226's phrase rather
than ADR-0204's.

**ADR-0226 §7's restatement of the three-group rule is partially superseded, and so is
ADR-0158 §5's clause behind it.** §7 states that *"**`Planner.plan`'s `memories` still
carries exactly three groups.** The planner is called before the servicer and receives
what it receives today"*, and gives the reason — *"the planner cannot be handed a group
produced from its own output"*. That reason is true of the **first** call and false of
the second: the fourth group exists by then, and it was produced from the first plan's
output rather than from the second's. A reader holding only ADR-0226 or only ADR-0158
would hand the second call three groups and would strip the very records the revision
exists to plan over. ADR-0070 §1's test is met on both. **The scope is that clause on
`Planner.plan`'s `memories` and nothing else of either section**: ADR-0158 §5's
grouping-not-ranking caution carries word for word to the fourth group on both calls;
its degraded-read clause, its episodic-bound clauses and its `Settings` prohibition
stand; ADR-0158 §4's append-never-interleave rule is extended in application and
unchanged in text; and ADR-0158 §5's sameness clause, as ADR-0226 already narrowed it,
is untouched here — on a turn that revised, `TurnResult.memories` still carries the
three groups followed by the appended fourth.

**ADR-0226 §8's trigger clause is partially superseded, narrowly, and the reason is
that it stops being a test a reader can run.** §8 rules that *"a turn on which
`read_request` is not `None` is a turn the trigger fired on, and a turn on which it is
`None` is a turn it did not"*, stated over the one plan a turn produced. On a revising
turn there are two, and the plan a consumer reaches — `TurnResult.plan` — is the
**last**, whose request may be `None` on a turn that fired. A reader holding only
ADR-0226 would read the trigger off it and record a fired turn as a non-firing,
depressing exactly the figure §8 exists to keep honest. **The scope is the reading of
that test and nothing else of §8**: the trigger is still the emission and nothing
else, every turn still writes a record, the third outcome is unchanged, the fire rate
is still a property of the planner, the population rules bind, and §8's prohibition on
calling anything here precision or recall binds the new figures too.

**ADR-0226 §3's second-level clause is partially superseded, and the deferral in the
same sentence is discharged.** §3 rules that a hop *"does not follow the evidence of a
record reached by that hop, and no lane adds a second level: that is iteration, and it
is §12's"*. §8 above admits a second level across iterations. The sentence both defers
the question and forecloses it in the meantime, so — following ADR-0226 §13's own
ruling on ADR-0208 §8 — the deferral is discharged **and** the clause is superseded,
*"in that order, and neither instead of the other"*. **The scope is the across-turn
case alone**: within one servicing a hop still follows exactly one level, and §3's
namer rule, its no-identifier rule, its ordinal scheme, its resolves-to-nothing rule
and its statement that a label is meaningful only within the call that rendered it all
bind entire and are what make the second level safe.

**ADR-0226 §9's durability sentence is not a clause this ADR moves, and the working
is shown because a review round reached for the other answer.** §9's marked block
reads *"The record holds **counts and kinds**, and copies no text … The ask stays
durable on the frozen `ActionPlan` (§4) and the record neither copies it nor points at
it."* The obligation there is on the **record** — copy nothing — and the sentence
about the ask is the **ground** for it rather than a second obligation binding some
other component to persist (ADR-0089 §2: a passage stating two separable obligations
is two clauses, and a statement of fact is not an obligation). It was already not true
of every turn when it was written: §11 item 10 requires a record from a turn *"rejected
for capacity, which `AssistantEngine` decides **after** the loop has planned and
serviced"*, which fired, serviced and persisted no plan. A reader holding ADR-0226 §9
copies no text before this ADR and copies no text after it — identical conduct, which
is ADR-0070 §1's test — so no record is owed. What **is** owed is saying that this ADR
enlarges the population by one shape, which §5 does and §14 defers.

**ADR-0226 §9 is applied rather than superseded, and §9 says so itself.** Its last
clause reads *"These are the fields milestone 2 **raises rather than replaces**. An ADR
admitting a second serviced emission per turn extends this record to account per
emission and keeps every field's meaning; it does not rename them, drop them, or start
a second audit beside this one."* §9 here does exactly that and nothing more. A reader
holding ADR-0226 alone, told to admit a second emission, is instructed by that sentence
to account per emission — identical conduct before and after, which is ADR-0070 §1's
test and the reason no record is owed. This is the same shape ADR-0226 §13 found for
ADR-0039 §10.

**ADR-0039 §10 is likewise applied and not superseded**, for the third time in this
corpus. §10's own sentence — *"every future shape change edits the annotation, which is
the intended friction"* — instructs a reader making a shape change to a record the
export carries to write the next integer, which is what §5 requires. ADR-0212 §8 and
ADR-0226 §4 each did the same and each recorded nothing; so does this.

**ADR-0014 §5 is applied and not superseded, and this is the record the store and
export clauses of §5 above answer to.** §5 rules that an export is *"complete and
internally consistent: every `goal_id`/`plan_id` referenced by an included record
resolves within the same export"*, and ADR-0049 §1 records how that promise is kept at
write time: *"`save_plan`'s app-level orphan check (ADR-0014 §5 rejects a plan whose
goal is unknown, so `export` can promise referential integrity without repair)"*.
`ActionPlan.supersedes` is a `plan_id` referenced by an included record, so §5's
sentence already reaches it by its own words: a reader holding ADR-0014 alone, adding
such a reference, makes it resolve and refuses a document in which it does not.
Identical conduct before and after is ADR-0070 §1's test, and it is the reason nothing
is recorded against §5 — the same shape ADR-0226 §13 found for ADR-0039 §10 and this
ADR finds again for it. What §5 above supplies is the *statement* that the new
reference is inside the promise, so an implementation does not read the existing
validator's silence as an exemption. `PlanStore` gains **no member**, and the widened
rejection set is flagged under golden rule 5 in §12 without being a decision this ADR
takes on its own account.

**ADR-0049 is untouched, and §1's foreign keys are not extended.** Its `REFERENCES`
constraints close a *cross-process* window — *"one connection deletes goal `g` between
another's check and its insert"* — which this reference does not have: both plans of a
turn are written by that turn oldest-first, `PlanStore` offers no single-plan delete,
`delete_goal` removes a goal's plans together and both share the goal. §5 above states
what would fire a durable constraint rather than adding one nothing needs.

**ADR-0014 §2's parenthetical is partially superseded, and only the parenthetical.**
§2 rules that *"Re-planning produces a *new* `ActionPlan` with a new `id` (the previous
one stays referenced by the `ExecutionState` that ran it), rather than mutating a plan
out from under an in-flight execution."* The rule is **untouched and load-bearing**:
§1 here produces exactly that new plan with that new id, and `frozen=True` is what
makes the pair an audit rather than an edit. What is false of an intra-turn revision is
the parenthetical: nothing ran the superseded plan, so no `ExecutionState` references
it, and a reader holding only §2 persists an orphan and loses the chain. **The scope is
that clause**; §2's capability-not-tool rule, its `JsonValue` reasoning and its
deep-freezing of `parameters` are untouched.

**ADR-0204 §4's first clause is reached further than ADR-0226 §13 reached it, and
recording it is the conservative reading.** §4 rules that on a bounded-audience
operation *"the supply the turn runs over, the plan it produces, the step that plan
drives, the `TurnResult` it returns, the reply composed for it and the plan persisted
through `PlanStore.save_plan` are all exactly what they are today"*. ADR-0226 §13
recorded the first, fourth and fifth of those and said in terms that *"The plan the turn
produces, the step that plan drives and the plan persisted through `PlanStore.save_plan`
are untouched — the planner runs before the servicer and its output is frozen"*. On a
turn that revises, all three of those change. A reader holding only ADR-0204 would
refuse to drive a second plan's step or to persist more than one plan, so ADR-0070 §1's
test is met. **The scope is those three, on a turn that revised, and nothing else**:
§4's **second** clause is untouched — no `TurnOutcome`, `TurnResult` or `SpokenTurn`
member gains, loses or changes meaning, because §10's carrier adds no `core` field —
and §4's narrowing prohibition stands entire, since §7 and §11 discard nothing.

**ADR-0037 is untouched, and this is the record a reader should check first**, because
#1908 and #1952 both expect it to move. Its clauses are *"This object disposes of one
step, once"* and *"`StepRunner` does not drive a whole plan."* Both are stated over the
step runner. After this ADR the engine still drives one step through one `StepRunner`
call; the only difference is which plan that step came from, and no clause of ADR-0037
says anything about which plan. A reader holding only ADR-0037, handed a revised plan,
disposes of its first step once — identical conduct, ADR-0070 §1's test, no record
owed. ADR-0037 §6's *"Re-driving a failed step is plan-level work"* and its `FAILED`
entry rule are likewise unreached, since no step here is re-driven. What **would**
move ADR-0037 is §14's plan-driving stage.

**ADR-0042 §3 is untouched, and the deferral it carries is not this deadline.** §3
defers *"an overall per-request deadline across a plan's steps"*, an *"overall deadline
the façade decrements and passes on as each step's *remaining* budget"*, and attaches
it to the plan-driving stage. §4's planning budget is a different object at a
different place: it bounds the turn's **planning** phase, before any step is driven,
it decrements nothing, it is not the `timeout` the adapter supplies, and it never
reaches `ToolInvoker.invoke` or `StepExecutor`. §3's per-attempt `timeout` keeps its
meaning entire and is threaded to the executor exactly as it is today. The two would
compose without conflict if the deferred one ever lands, and neither is a
reparameterisation of the other.

**ADR-0203 §§1 and 2 are untouched, for ADR-0226 §5's reason inherited whole.** Both
bind an operation whose output channel's audience is unbounded; §2(c) refuses to
revise where §5 refused to service, so no revised turn exists on such an operation.
§2's backfill clause — a read *"shaped by what was withheld"* — is not approached, and
this ADR adds no second filter application anywhere.

**ADR-0208 §1 is untouched, including the clause ADR-0226 moved.** ADR-0226 superseded
§1's one-site clause to admit a second relevance-selection site; a turn's two sighted
queries are two calls **at that same site**, which §1's own scoping sentence covers as
written: *"One site is not one call."* §1's keyed-load clause is likewise untouched and
is what a `CITATION_HOP` remains at every iteration, and both tool clauses are honoured
rather than avoided — nothing here is a tool, is registered, or is reachable through a
`ToolRegistry`.

**ADR-0211 is untouched and §3 is applied.** §3 requires the capability vocabulary to
be read *"immediately before the call"*; §1 reads it before **each** call, which is that
clause obeyed rather than extended. §1's required-and-undefaulted reasoning is
untouched and this ADR's own defaulted field is distinguished from it exactly as
ADR-0226 §4 distinguished its own.

**ADR-0223 is untouched in both directions, and §7's monotonicity is why.** §2's
one-computation-per-pass rule already places the value *"immediately after the turn is
in hand and before anything is driven"*, which on a revising turn is after the last
iteration, over the final supply. §6's egress allow and its product sentence apply to a
revised turn verbatim. And the failure `SelectionOrigin.over`'s docstring warns
about — *"re-plan over clean material, stamp the binding from the last selection, and
watch the fact clear"* — is foreclosed by construction rather than by a clause, because
the supply only grows.

**ADR-0227 is untouched and is relied on.** §1's render rule is stated over *"a record
**this turn's** citation hop reached"* and §3's carrier over *"the distinct records the
hop resolved that the turn's supply holds after servicing"* — both stated over the
turn, so a turn with two servicings accumulates one set across both, in ADR-0226 §6's
order, and §4's cap of ten reply lines is taken over that one accumulated set. That is
§3 read as written; the risk is an implementation that keys the carrier on a servicing
and lets the second replace the first, which §13's fourteenth test is written against.
§7's test-fidelity rule binds this ADR's own tests 2 and 3.

**ADR-0170 §2 and §5a are untouched.** The composing stage still holds no
`MemoryStore`, performs no second retrieval and no second context assembly, and renders
step accounts from closed vocabularies alone; §10's fact is given to the stage as an
input, exactly as ADR-0203's withholding fact already is, and adds no member to §5a's
vocabularies.

**ADR-0226 §10's no-bump clause is not superseded**, and the distinction is worth
stating because §6 contradicts its premise. That clause is stated over ADR-0226's own
two lanes — *"Neither lane moves `PROTOCOL_VERSION`"* — and both have merged. A reader
holding only ADR-0226 and implementing **that** ADR does what it says; a reader
implementing **this** one is bound by §6. What ADR-0226 §4 and §10 assert as a fact
about the tree is false, and §15 records that against ADR-0226's header as an appended
dated note rather than as a supersession, because it changes no decision ADR-0226 made:
its lanes ran and are done. The consequence for the released version is #1956, not
a clause.

**ADR-0176, ADR-0199, ADR-0217 and ADR-0225 are untouched.** A revision may be a
decline and takes ADR-0176 §6's path unchanged; ADR-0199 §1's audience is used as
ratified and §4 explains why it is not this budget's key; ADR-0217's placement field is
read where it lives; and ADR-0225 §12's gate is neither approached nor prepared for
(§12).

**Everything else this ADR cites is used as ratified**: ADR-0004 §7; ADR-0014 §§1, 2 and
5; ADR-0015 §5; ADR-0027 and ADR-0070 §§1, 3 and 4 for the supersession form; ADR-0039
§10; ADR-0072 §5; ADR-0074 §5; ADR-0082 §1; ADR-0088 and ADR-0089 for the citation forms
and the marks; ADR-0093; ADR-0113 §5; ADR-0119 §4; ADR-0124 §9; ADR-0137 §§1 and 2;
ADR-0158 §§4 and 5; ADR-0187 §4; ADR-0199 §§1 and 3; ADR-0204 §§2 and 4; ADR-0208 §1;
ADR-0210 §1; ADR-0213 §11; ADR-0221 §5; ADR-0224 §1; ADR-0226 throughout; ADR-0227 §§1,
3, 4 and 7.

**And two records about form rather than substance.** #1908's milestones are numbered
globally, 27 to 30, on the owner's ruling of 2026-09-03; ADR-0226 and ADR-0227 were
written before it and say "milestone 1" and "milestone 2", so each gains an appended
dated header note giving the mapping, because ADR-0070 §1 permits no rewrite of
ratified text. Nothing either ADR decided changes. And ADR-0226's `Status` line takes
the leading `Partially superseded by` token for the first time, so under ADR-0082 §2
its amendment qualifier — *"§11 item 1 amended by ADR-0227"* — comes **off** that line,
where ADR-0070 §4's extraction invariant would otherwise read `ADR-0227` as a
supersession target. Its record stands whole in the `Amended: 2026-09-03 by ADR-0227`
note directly above, which is ADR-0082 §2's own remedy — *"An amendment on a
leading-token line is recorded in full; it is simply recorded four lines lower"* — and
ADR-0080 §8's operation generalised. Nothing is lost by the move, and ADR-0227 is
neither superseded nor amended here.

**And one honest note on what this ADR is ratified without.** ADR-0015 §5 admits that
*"a contract ratified with no implementation contact is how a seam that does not survive
first use gets blessed"*, and this decision inherits that risk twice over: the seam it
extends has itself failed two live probes, and its own justification — a step whose
parameters depend on a read — has never run. The mitigations are §12's ordering, which
holds the implementation until milestone 27's exit is ruled, and §13's first test,
which is written to fail if revision is wired but not working.

## Consequences

- **A turn can look, learn and decide**, which is the first time in this system that
  anything read has been able to change what the turn does rather than only what it
  says. That is the capability #1844's end-state section names first and the one
  #1908's charter says the exit is on.
- **A turn may cost two model round trips**, on up to the fire rate's share of turns.
  §4's budget bounds when a second is started and §9 measures how often each guard
  fires; neither bounds a turn already in flight, and §14 defers the one that would.
- **The audit becomes a per-emission account.** The fire rate keeps its meaning and
  stays comparable to the replay's 13.6%; the iteration rate and the stop distribution
  are new and are labelled for what they are.
- **`PROTOCOL_VERSION` moves and a hub redeploy is owed**, and the move exposes that
  ADR-0226's own field shipped without one. Repairing that window is a separate issue;
  what this ADR guarantees is that its own field does not widen it.
- **A plan store holds more plans.** Every turn that revises persists two, and a reader
  can follow `supersedes` to reconstruct what the system decided and then decided
  again.
- **The prompt can be twenty serviced records wider.** That is on top of a belief
  budget and an episodic supplement of thirty, and it is the honest cost of a budget
  per servicing rather than a share.
- **`planning/`'s production code does not change at all**, which is the surprising
  consequence and the measure of how much ADR-0226 got right: the planner already
  emits a request beside its plan, and asking it twice needs nothing new from it.
  What does change is what the `Planner` contract *documents* — four groups on a
  second call, and two requests in one turn — which is flagged as a breaking change
  under golden rule 5 and held by the shared `PlannerContract` rather than by prose.
- **Revisit when** §9's stop distribution shows the budget firing often or never; when
  the iteration rate shows the second emission is a different facet rather than a
  follow-up (§14's decomposition trigger); when a bounded-audience spoken surface is
  declared and §4's budget stops being hypothetical; or when the plan-driving stage
  lands and the harder half of revision — after an act — becomes decidable.

## Alternatives considered

**Revise after a driven step, so that step two depends on step one's output.**
*Rejected here and deferred rather than refused.* It is the literal reading of #1908's
first exit clause and it is the more ambitious mechanism. It needs the plan-driving
stage ADR-0037 named as "the next slice" and everything that stage owes: step ordering,
a producer for `UNMET_DEPENDENCY`, cancellation, parking mid-plan with #257 open
against it, `INDETERMINATE` in the middle of a plan, and ADR-0042 §3's decrementing
per-request deadline. It also inverts the engine's shape, since the planner call is
inside the loop and the drive is above it. Each of those is a decision; taking them
together with this one would be several ADRs presented as one, and the milestone is
chartered as *"the largest single decision on the track"* rather than as four.

**Revise in place: mutate the plan the turn holds.** *Rejected.* ADR-0014 §2's
`frozen=True` forbids it, and its reason is the whole of why: a plan that can be edited
after the fact *"is not an audit record"*. It would also mean assembling a plan in code
rather than at the `Planner.plan` seam, which would make the revision a derivation
rather than a judgement.

**Persist only the plan the turn drove.** *Rejected*, and it is the alternative that
looks cheapest and costs the most. ADR-0226 §9 retains no ask text on the strength of
one sentence — *"The ask stays durable on the frozen `ActionPlan`"* — and §10 reads the
fire rate off persisted plans. The ask that was actually serviced is on the plan a
revision replaces, so discarding it makes both of those false on the day this ships.

**Infer the revision chain from `goal_id` and `created_at` instead of adding a field.**
*Rejected on the contract rather than on taste.* It is true of the tree today and false
of ADR-0014 §1, which rules that a goal *"outlives any one conversation"*: a later
turn's plan for a resumed goal would be indistinguishable from a revision. An audit
chain that holds only while an implementation detail holds is not an audit chain.

**One record budget shared across the turn's servicings.** *Rejected.* A sighted query
can take the whole budget on its first firing, so the second servicing would ordinarily
receive nothing, and the second emission would be a fire-rate numerator with no read
under it — the failure ADR-0226 §11 item 11 names for the empty request, reached by
another route.

**Tell the planner it is on its last look.** *Rejected.* It would make the second
emission a function of the bound rather than of the supply, which is what ADR-0226 §8
forbids for the trigger generally, and it would make the two emissions of a turn
incomparable to each other and to milestone 27's. It also adds a parameter to a seam
that needs none.

**Key the planning budget on the channel's audience rather than on the operation.**
*Rejected.* Two operations of one audience tolerate very different waits — a streaming
browser turn and a worn earpiece are both bounded-audience under ADR-0199 §1 — and
ADR-0199's own argument against keying on modality is an argument against overloading
audience with a second question.

**A wall-clock deadline that cancels a planner call in flight.** *Rejected for now and
deferred by name.* It bounds what a gate on starting cannot — a single slow model call
— but it needs a posture for abandoning work already paid for and a rule for what a
half-composed plan is, neither of which this decision needs to take. §4 states the
resulting overrun as an accepted cost rather than hiding it.

**Admit several asks of one kind now, so a compound question is decomposed in one
emission.** *Rejected and deferred.* Iteration already gives a second ask of each kind,
with sight of the first's yield, which is strictly better informed than two blind asks;
and admitting *n* asks reopens ADR-0226 §6's budget and precedence, which is a second
decision this one does not need.
