# 144. Selection prefers the least severe capable declaration, and opens no question of its own

- Status: Proposed
- Date: 2026-08-13
- **Not a contract change, and it ships alone anyway.** No Protocol is added or
  altered, no `core` type gains or loses a member, and `core/config.py` is
  untouched. `Disposition.AMBIGUOUS_CAPABILITY` keeps its name and its shape;
  what §6 narrows is what it reports. This ADR nonetheless **partially
  supersedes** a ratified decision (ADR-0037 §1) and **discharges** a deferral of
  another (ADR-0016 §7), so both required lenses are run on it and the
  implementation is a separate lane briefed after this merges (§8).
- **Durability clause.** Every quotation below — from an ADR, from
  `core/protocols.py`, from `core/types.py`, from `src/ai_assistant/` or from an
  issue — is of its text as it stood at this ADR's base, `b7ced50c`, not of its
  text on any later day. Every ADR this decision composes with reads `Accepted`
  there, bar ADR-0016, which reads `Accepted, partially superseded by ADR-0018`
  in the scope its own header names. The `Date` line is this ADR's authoring date
  in this clone's frame; the base named here is the anchor that does not move
  under either frame.

## Context

### The question, and who left it open

Issue #241 is the charter, and it is a hole three ratified ADRs each deliberately
declined to fill:

- **ADR-0016 §5 refused it to the registry.** `ToolRegistry.find` returns every
  capable declaration, ordered by `id`, and the section says why the order means
  nothing: *"some total order must be specified"*, and *"ordering by risk would
  be the beginning of ranking, and a caller would come to depend on it"*. The
  `ToolRegistry` docstring in `core/protocols.py` carries the same sentence —
  *"The registry does not choose."*
- **ADR-0016 §7 deferred it to us, by name.** *"Which candidate to prefer among
  several — and how risk, cost and latency trade off — belongs to the selection
  stage in `orchestration`, informed by `permissions`. This ADR supplies the
  inputs."*
- **ADR-0037 §1 declined to invent it.** `StepRunner` runs a step when `find`
  returns exactly one candidate; with several it returns `AMBIGUOUS_CAPABILITY`
  and leaves the step `PENDING`, because *"taking `candidates[0]` is the obvious
  implementation and it is a ranking rule in disguise"*. It rejected *"a `select`
  hook or an injected ranker"* on ADR-0036 §1's ground, and said what it was
  leaving behind: *"The selection rule is issue #241; when it exists it is a
  rule, not a parameter."*

ADR-0029 §7 restates the same deferral from the invocation side. So the shape of
the answer is heavily constrained before it is written: it must be a rule, fixed
here rather than supplied by a caller; it must not move ranking back into the
registry; and it must not collapse the `planning → tool selection` boundary
ADR-0014 §2 spends a section defending, where *"a step names a capability, not a
tool"* precisely so that *"the later tool-selection stage picks the concrete tool
by weighing the `risk_level`/`reversibility`/`cost` metadata"*.

### What the tree actually holds, read at the base

Each of these was read at `b7ced50c` rather than recalled.

- **`StepRunner.run`** (`src/ai_assistant/orchestration/runner.py`) resolves the
  step's capability, calls `find`, and branches on the length of the result. On
  `len(candidates) > 1` it commits **nothing** — no plan-store transition, no
  `ActionPolicy` call, no audit record — logs `step_capability_ambiguous`, and
  returns `StepDisposition(Disposition.AMBIGUOUS_CAPABILITY, state)` on the
  caller's own unchanged state. `candidates[0]` is reached only in the
  single-candidate branch.
- **`Disposition`** is a `StrEnum` in `core/types.py` with exactly five members:
  `EXECUTED`, `DENIED`, `AWAITING_CONFIRMATION`, `NO_CAPABLE_TOOL`,
  `AMBIGUOUS_CAPABILITY`. **`StepDisposition`** is a frozen dataclass in
  `orchestration/runner.py` — ADR-0037 §4's *"frozen dataclass in
  `orchestration`"* that *"crosses no subsystem boundary"* — carrying the
  disposition, the state, and optional `decision_id`, `tool_id` and `decision`.
- **`resolve_capability`** (`orchestration/capability_alias.py`) runs *before*
  `find`, folding a planner's synonym onto an advertised capability name. It
  declines to fold where the fold would be ambiguous, on the stated ground that
  *"resolving it would silently rank them"*, and it does not weaken ADR-0037
  §1's refusal.
- **`ThresholdActionPolicy.decide`** (`permissions/policy.py`) reads
  `request.tool` and nothing else — never `request.parameters`. Its two
  non-configurable floors are a non-empty `discloses` and a `CostBasis.UNKNOWN`
  cost, each forcing `CONFIRM`; its four user thresholds are constructor
  arguments over `RiskLevel` and `Reversibility`, and the ruling is the maximum
  outcome any clause reached.
- **`ToolDefinition`** carries `latency: timedelta | None`, validated
  non-negative and documented *"advisory, not a timeout"*. **Nothing reads it.**
  ADR-0016 §4 declared it *"for the selection stage"*; the selection stage has
  never existed as anything that weighs.
- **`build_default_registry`** (`tools/builtin.py`) registers exactly two tools,
  `current_time` and `recall_memory`, advertising two different capabilities. So
  **`AMBIGUOUS_CAPABILITY` is unreachable in the shipped registry today**, and
  this ADR decides a rule that nothing in `main` can currently exercise.

### Why it is due now, and what it has to serve

`docs/roadmap.md` item 12 is *"Actuators, in bulk. MCP-shaped tool breadth,
behind the decisions it forces: ranking among capable tools (#241 …)"*. The rule
therefore has to be stated for a registry that will hold **many discovered
declarations**, most of them written by someone else, several of them advertising
the same capability with metadata that is identical field for field. A rule tuned
to two hand-written tools would be a rule that ties on its first real day.

The leg's exit test is the second constraint, and it is sharper than it looks:
*"the assistant completes a task that changes something in the world, and the
user was asked exactly once, at the moment it mattered."* **Exactly once** is a
ceiling as well as a floor. A selection stage that asks *"which tool?"* and then
lets the permission stage ask *"may I?"* has asked twice about one step, and the
first of those two questions is one the user is least equipped to answer — they
are shown two declarations differing in fields whose meaning is the permission
layer's, not theirs.

### What the corpus has already ruled out, which is most of the design space

- **An injected ranker, comparator or `select` hook** — ADR-0037 §1, on ADR-0036
  §1's ground. ADR-0036 §1 rejected user-supplied clauses because *"an injected
  non-monotone predicate produces a non-conforming policy out of a conforming
  class"*, and stated the discriminating test in one sentence: *"The
  configuration surface is four ordered scalars precisely because every value of
  them is safe."*
- **Ranking in the registry** — ADR-0016 §5.
- **Preferring by `id`** — ADR-0037 §1, which named the concrete harm: a rule
  picking by name *"would silently prefer `a_deleter` over `b_archiver` for the
  same capability — choosing between two side-effecting actions on an
  alphabetical accident"*.
- **Validating `step.parameters` against `tool.parameters_schema`** — ADR-0016
  §7, ADR-0029 §7 and ADR-0037 §1 all defer it pending a JSON Schema runtime
  dependency, so no candidate can be preferred, or excluded, on argument fit.

## Decision

We will fix the selection rule **here**, as a total ordering over declarations
that reads only fields `ToolDefinition` already carries, and run the unique
minimum. Selection consults no policy, opens no prompt, and consumes no
caller-supplied rule.

### 1. The rule: order the candidates, run the unique minimum

> **Normative.** The selection stage orders the candidates `ToolRegistry.find`
> returned by the key defined in §2, §3 and §4, applied lexicographically in that
> order, and selects the candidate that is strictly least under it. Where the
> least candidate is not unique — two or more candidates equal under the whole
> key — the stage selects nothing and §6 governs the disposition.

> **Normative.** The ordering is a **total preorder** computed from the candidate
> declarations and the §4 preference sequence alone. Every key in it is a total
> function of one declaration onto a totally ordered value, so the ordering is
> transitive and the selected candidate does not depend on the order in which
> `find` returned the candidates, on how many times the stage is run, or on any
> clock, random source or stored state.

Two properties of that statement carry the whole design and are worth separating
from it.

**The minimum must be *unique*, not merely *first*.** "Take the first minimum
found" is one word shorter and it reintroduces exactly what ADR-0037 §1 refused:
where two candidates tie, the winner is whichever `find` listed first, and `find`
lists by `id`. A rule that resolves ties by iteration order is a rule that
resolves ties by name, spelled so that nobody can see it. So a tie is a genuine
outcome of the rule rather than a case the implementation absorbs.

**Every key is total, and that is a correctness requirement rather than
tidiness.** A key that declines to compare some pairs — "an undeclared latency is
not comparable with a declared one" — makes the composed ordering
non-transitive: with `A(1s)`, `B(undeclared)` and `C(5s)`, `A < C` while `A ~ B ~
C`, and which candidate comes out minimal then depends on the traversal. §3 pays
a small price in each key to keep this property, and says where.

> **Normative.** The ordering does not read `ToolRegistry.find`'s `id` ordering,
> and `id` is not a key at any position. ADR-0016 §5's ordering is unchanged and
> stays what it was ratified as — a specified total order carrying no meaning.

### 2. The severity block: the axes a conforming policy already ranks, in the same direction

The first four keys, applied in this order, are the fields on which every
conforming `ActionPolicy` is contractually constrained. Lower is preferred
throughout.

> **Normative.** Key 1 is `risk_level`, ascending under `RiskLevel`'s declaration
> order (ADR-0016 §2). Key 2 is `reversibility`, ascending under
> `Reversibility`'s declaration order. Key 3 is `discloses`, compared
> **lexicographically** as a sequence under `DataTier`'s declaration order, so
> the empty tuple is least and a proper prefix is less than its extension. Key 4
> is `cost.basis`, ordered `FREE` < `PER_CALL` < `UNKNOWN`.

Key 3 needs its shape stated once because two readings of "narrower disclosure"
are available and they disagree. `discloses` is sorted most-sensitive-first and
de-duplicated at validation (ADR-0016 §3), so the tuple is already canonical;
comparing it elementwise makes the most sensitive tier dominate — `(SECRET,)` is
worse than `(PERSONAL, OPERATIONAL)` — and makes a shorter tuple win against its
own extension, so `(PERSONAL,)` beats `(PERSONAL, OPERATIONAL)`. Both readings
are what a person means by "discloses less".

**This is the whole of what ADR-0016 §7's "informed by `permissions`" is
discharged as, and the discharge is by *agreement* rather than by
consultation.** ADR-0021 §5 requires of every policy that *"raising `risk_level`,
raising `reversibility`, or widening `discloses` — with everything else held
equal — must never produce a less restrictive outcome"*, and fixes two absolute
floors: a non-empty `discloses` *"may not receive `ALLOW` with `authorised_by`
unset"*, and *"An `UNKNOWN` cost is never auto-granted"*. `ThresholdActionPolicy`
reads `request.tool` and nothing else, so the policy's domain and this ordering's
domain are the same object. The consequence is structural: **where one candidate
is less severe than another on every key of this block, no conforming policy
rules on it more restrictively.** Selection therefore never hands the gate a
candidate that a dominated alternative would have got past more easily, and it
does so without calling anything.

Keys 1 and 2 lead because they are the axes ADR-0014 §2 and ADR-0016 §7 both name
as the point of having a selection stage at all, and because `risk_level` is the
author's own summary judgement of severity — ADR-0016 §1 makes it required
precisely because *"`risk_level` has no defensible default"*. Ordering disclosure
above them was considered and rejected: it would prefer a `CRITICAL`-risk tool
that discloses nothing over a `LOW`-risk tool that discloses one `OPERATIONAL`
tier, which reads wrong because it is wrong.

Key 4 does double duty and the two halves have different authorities. Its top end
— `UNKNOWN` last — is ADR-0021 §5's floor read as a preference: a candidate whose
author *does not know* what a call costs can never be auto-granted, so preferring
a candidate that declared over one that did not is preferring the one that can
run without a prompt. Its lower end — `FREE` before `PER_CALL` — is a plain
economic preference with no policy clause behind it, because spend accumulation
is deferred (ADR-0021 §6).

> **Normative.** Amounts are never compared. Two `PER_CALL` candidates are equal
> under key 4 whatever their `amount` and `currency`.

Comparing amounts is the obvious refinement and it cannot be made total.
ADR-0016 §4 rules cross-currency comparison out of scope — *"A policy comparing
amounts across currencies needs conversion rates and is out of scope entirely"* —
so an amount key could only compare within a currency, which is the
partial-comparison trap §1 forbids. A rule that prefers the cheaper of two USD
tools but cannot rank a USD tool against a EUR one is not an ordering, and the
transitivity failure surfaces as name-order dependence rather than as an error.

> **Normative.** `reads`, `writes`, `side_effecting`, `idempotency`,
> `idempotency_window`, `description` and `parameters_schema` are not keys at any
> position.

ADR-0036 §1 rejected policy clauses keyed on `reads`, `writes` and
`side_effecting` because *"All four are readable and none has a rule to be part
of yet"* — and, more sharply, because a clause outside the set ADR-0021 §5 states
monotonicity over *"would be unexercised by the contract, which is where a
monotonicity inversion could hide"*. The same argument transfers exactly: a
selection key on an axis the policy is not constrained over is a key whose
direction nothing checks. `idempotency` is a retry guarantee, which is the
executor's concern (ADR-0029 §5) and not a severity axis; `parameters_schema` is
the deferred fit question.

### 3. Key 5, latency: the operational tie-break, with absence sorted last

> **Normative.** Key 5 is `latency`, ascending among candidates that declare one,
> with an undeclared `latency` (`None`) ordered **after** every declared value.

`latency` exists for this and has never been read (Context). Placing it below the
severity block is what keeps it honest: it only ever decides between candidates
already equal on every axis a policy is constrained over, so a wrong or
optimistic estimate wins a speed race and nothing else. ADR-0016 §4 already
called it *"[a]dvisory as to its accuracy — it is not a timeout and nothing
enforces it"*, and this is a use that survives that caveat.

Absence sorts last rather than first, and rather than incomparably. Incomparably
is forbidden by §1. First would reward omission — an author who declares nothing
would outrank one who declared a real number — which inverts the incentive
ADR-0016 §1 built the whole type around, where *"a tool that does not declare its
reach does not load"*. Last is the remaining option and it is the one that reads
correctly: an estimate nobody gave cannot beat an estimate somebody gave.

### 4. Key 6, the user's preference — and why a knob is safe *here* and nowhere above it

> **Normative.** Key 6 is the position of the candidate's `id` in an ordered
> **preference sequence** of tool ids supplied to the selection stage at
> construction by the composition root. A candidate whose `id` appears in the
> sequence is ordered by its index; a candidate whose `id` does not appear is
> ordered after every candidate whose `id` does. The sequence defaults to empty,
> in which case key 6 ranks every candidate equally.

> **Normative.** The preference sequence is consulted **only** at key 6. It can
> never promote a candidate over one that the ordering prefers at keys 1 through
> 5, and the selection stage exposes no other route by which a caller may
> influence which candidate is chosen.

This is the key that makes the rule usable rather than a rule that stalls, and it
is the one that has to answer ADR-0037 §1's rejection of an injected ranker
without evading it. The rejection is answered rather than evaded, and ADR-0036
§1's own test is the discriminator.

**What was rejected there is a *rule*; what is supplied here is a *datum*.** A
`select` hook or a comparator hands the caller the question — the caller decides
what "better" means, and a caller that decides badly produces an unsafe selection
out of a safe stage. That is precisely ADR-0036 §1's *"an injected non-monotone
predicate produces a non-conforming policy out of a conforming class"*. The
preference sequence decides nothing of the sort: the rule is fixed above it in
full, the sequence is consumed at one position the rule defines, and it is
consulted only after every safety-bearing key has already been applied and found
the candidates equal.

**So every value of the knob is safe, which is the exact property ADR-0036 §1
required of a configuration surface.** A preference sequence orders candidates
that are equal in `risk_level`, in `reversibility`, in `discloses` and in cost
basis. Two such candidates are indistinguishable to every conforming policy —
ADR-0021 §5's monotonicity holds *"everything else held equal"*, and here
everything else *is* equal — so no ordering of them can make an action more
dangerous, reach a different permission outcome, or turn a conforming policy
non-conforming. There is no bad value to supply.

The composition root passing it in is ADR-0036 §1's own precedent, taken
deliberately: the policy's thresholds *"are the user's configuration and belong
in `Settings` eventually"*, and a stage that read global configuration itself
*"would stop being the injectable, deterministic object the conformance suite
relies on"*. The same holds here, and the same follow-on is owed — wiring the
sequence to a user-facing surface, so a preference is something the user states
rather than something an operator edits, is §7's deferral and issue-tracked.

> **Normative.** The preference sequence is configuration and is never consent.
> Nothing in it grants, authorises or relaxes any permission outcome, and no
> implementation may read it as an authorisation, populate
> `PermissionRuling.authorised_by` from it, or use it to skip the permission
> stage.

ADR-0093 §7's *"configuration is not consent"*, as ADR-0097 §8 enforces it for
source grants, is the reason that clause is written rather than assumed. A
sequence naming a tool is a statement about which of two equals to run, not a
standing grant to run it — those are ADR-0021 §6's, still deferred, and they
travel through `authorised_by` rather than through here.

### 5. Selection opens no question, and a refusal is not a re-selection

> **Normative.** The selection stage puts no question to the user. It prompts for
> nothing, surfaces no choice, and produces no confirmation of its own. The only
> question a step raises is the permission confirmation ADR-0037 §4 already
> governs.

The exit test's *exactly once* is what this clause buys, and it costs nothing to
buy because the machinery is already there. A `CONFIRM` parks the step and the
user is shown a `Confirmation` carrying `tool_id`, `tool_description`,
`parameters` and `reason`; the recorded decision embeds the whole
`ToolDefinition` by value (ADR-0021 §1). So the chosen tool **is** in front of
the user at the one moment they are asked, named and described, and answering the
question they are already being asked is how they accept or refuse it. A separate
"which tool?" prompt would add a second question about one step, and would ask it
about fields — a tier tuple, a reversibility scale — whose comparison is exactly
what this ADR exists to have already done.

> **Normative.** A `DENY`, or a confirmation the user refuses, disposes of the
> step per ADR-0037 §2 and §5. It is never a signal to select the next candidate,
> and the selection stage does not re-run against the remaining candidates within
> the same step.

Retrying the next candidate is the tempting fallback and it breaks the ceiling
directly: a user who refused one tool is asked again about a second, for one
step, having said no once. It is also a misreading of the refusal. A `DENY` is
the user's policy refusing an *action* whose severity it read off a declaration;
the runner-up is a candidate the ordering already judged **at least as severe**,
so under ADR-0021 §5 no conforming policy rules on it less restrictively. The
fallback is a second prompt whose answer is knowable in advance.

> **Normative.** Selection happens once per step. `StepRunner.resume` does not
> re-select: it rebuilds the request from the confirmation's own embedded
> declaration, as ADR-0037 §4 already requires.

ADR-0037 §4 step 3 established that for the substitution reason — the tool that
runs after a confirmation is *"the declaration the user was shown, read out of
the record, never re-resolved through the registry"*. Under a selection rule that
reason gains a second half: a registry populated differently between the prompt
and the answer could otherwise order the candidates differently, and the user's
"yes" would authorise a tool they were not shown.

### 6. `AMBIGUOUS_CAPABILITY` is narrowed, not superseded, and it now means something a surface can act on

> **Normative.** ADR-0037 §1's several-candidates row is superseded to this
> extent and no further: a step is no longer refused whenever `find` returns more
> than one candidate. `Disposition.AMBIGUOUS_CAPABILITY` is **retained**, with
> its meaning narrowed to the residue §1 defines — two or more candidates equal
> under the whole ordering, including key 6. Every other clause of ADR-0037
> stands unchanged.

> **Normative.** In that residue the durable effect is unchanged and remains
> ADR-0037 §1's: nothing is committed, no policy is consulted, no decision is
> recorded, and the step stays `PENDING`.

The residue is not a rounding error, and pretending otherwise would be the
easiest way to get this ADR wrong. With MCP-shaped breadth (roadmap item 12),
several servers advertising one capability with identical metadata — `MEDIUM`
risk, `REVERSIBLE`, one disclosed tier, `UNKNOWN` cost, no declared latency — is
the *ordinary* case, not the exotic one. Keys 1 through 5 will tie on it. Key 6
is what resolves it, and the residue is what is left when the user has expressed
no preference between things nothing else can tell apart.

Keeping `AMBIGUOUS_CAPABILITY` for that is the honest reading of ADR-0037 §1's
own argument rather than a leftover: *"No `SkipReason` is true of it"* remains
true, `PENDING` remains *"already the truth about this step"*, and a tie broken by
`id` would still be *"choosing between two side-effecting actions on an
alphabetical accident"*. What changes is that the disposition now reports
something a surface can do something about — the candidates are known to be
equivalent on every axis the system can reason over, so the only outstanding
question is which one the *user* prefers, and that is a question with a durable
answer.

> **Normative.** `StepDisposition` carries the ids of the tied candidates on an
> `AMBIGUOUS_CAPABILITY` disposition. This is a field on the frozen dataclass in
> `orchestration`, which ADR-0037 §4 states *"crosses no subsystem boundary"*; no
> `core` type and no Protocol changes for it, and `Disposition` gains no member.

### 7. What this does not decide

Each is scoped out with its reason, because scoping something out is a decision.

- **Argument fit as a selection input.** ADR-0016 §7 and ADR-0029 §7 defer
  validating `step.parameters` against `parameters_schema` pending a JSON Schema
  runtime dependency, and this ADR does not take that on. One clause about its
  eventual shape is set here because getting it wrong later is expensive:

  > **Normative.** When parameter-schema enforcement lands, a candidate whose
  > schema the step's parameters do not satisfy is **ineligible** and is removed
  > from the candidate set before any key of §2 through §4 is applied. It is
  > never a key, a penalty or a tie-break term.

  That is ADR-0128 §1's shape — every eligibility predicate binds before the
  ranking cut — applied to the one predicate this stage knows is coming. A fit
  term folded into the ordering would let a well-declared candidate that cannot
  accept the arguments outrank one that can, which is a ranking answering a
  question about eligibility.
- **Capability namespacing.** ADR-0016 §5 leaves capability names *"flat
  strings"* and §7 defers namespacing until *"collisions between integrations
  become real"*. This ADR does not close it and it makes it more urgent, which
  §Consequences states plainly rather than burying: before this rule a name
  collision stalled the step; after it, a collision resolves silently to the
  less severe of two declarations that mean different things. Issue filed.
- **A durable, user-facing tool preference.** §4's sequence is composition-root
  configuration, which is an operator's surface rather than a user's. Making a
  preference something the user states once and the system keeps needs durable
  per-user policy state with its own data-rights obligations — the same store
  ADR-0021 §6 defers for standing grants, and adjacent enough that settling them
  together is likely right. Issue filed. Note what is *not* deferred: the rule
  above works with an empty sequence, so nothing is blocked on it.
- **A learned preference.** Preferring the tool a user's past feedback favours is
  the project's own thesis pointed at this seam, and it is refused here for
  ADR-0036 §1's reason rather than out of caution: a learned ranker is a
  predicate whose values are not all safe, sitting immediately upstream of a
  safety gate, and its ordering would not be a total function of the declarations
  that anyone could check. The sanctioned path is the same as §4's — a preference
  the user *stated*, which is a decision on the record, not one inferred from
  behaviour.
- **Asking the model to choose.** Rejected outright. It is non-deterministic, so
  §1's ordering guarantee would not hold; it is unauditable, since no recorded
  fact explains why one tool ran; and it collapses `planning → tool selection`
  from the far side — the model already produced the plan, and letting it also
  pick the tool makes ADR-0016's declared metadata decorative, which is the
  hard-coding ADR-0016 §1 exists to remove.
- **Standing grants and spend accumulation** (ADR-0021 §6), **per-call data
  reach** (#57) and **enablement** (ADR-0016 §7). Unaffected and still deferred.

### 8. What the implementing lane owes

> **Normative.** The implementation is a separate lane and a separate PR, briefed
> after this ADR merges. It changes no file under `src/ai_assistant/core/` and no
> Protocol.

> **Normative.** That lane's tests pin, at minimum: each key of §2 through §4
> deciding in isolation with all other keys held equal; the lexicographic
> composition, including a case where a later key is decisive and one where an
> earlier key overrides a later one that disagrees; `discloses` compared as a
> sequence, with the empty tuple least and a proper prefix beating its extension;
> two `PER_CALL` candidates equal under key 4 whatever their amounts and
> currencies; an undeclared `latency` losing to every declared one; a preference
> sequence failing to promote a candidate the severity block ranks lower; a tie
> under the whole key producing `AMBIGUOUS_CAPABILITY` with nothing committed;
> and — because §1's transitivity guarantee is the one an implementation is most
> likely to lose — the same candidate selected from the same set presented in
> reversed and shuffled orders.

### 9. Status, and the review this ADR ran

This ADR was drafted, reviewed and revised while `Proposed`, and flipped to
`Accepted` only once the whole required set came back green on one tree, with
that set re-run on the flipped tree. `CONTRIBUTING.md` → "Finishing an ADR PR:
`Proposed` through the reviews, `Accepted` on the way out" owns that sequence and
is the pointer rather than a re-derivation of it. The set run was **adversarial
and architecture**, both required here for the reason the header gives. Nothing
implements against this ADR until it has merged (ADR-0015 §5, golden rule 5).

## Consequences

- **#241 closes, and the stall ADR-0037 §1 accepted ends for every case the
  system can reason about.** A deployment registering two tools for one
  capability now runs one of them, chosen by a rule that is written down, rather
  than producing ADR-0037's *"my plan did nothing"*.
- **`latency` acquires its first reader**, four months after ADR-0016 §4
  declared it *"for the selection stage"*. It is the weakest key in the ordering
  and sits where a wrong value costs least.
- **Nothing in `main` exercises this on the day it lands.** The shipped registry
  holds two tools advertising two capabilities, so the rule is unreachable until
  leg 12's breadth arrives. That is the ordinary contract-first position — the
  rule lands before the tools that need it — and it is also the honest risk:
  this decision has had no implementation contact, and the first real MCP
  registry is what tests whether the tie residue is rare or routine. §6 predicts
  routine.
- **The rule rewards under-declaration, and this is new.** ADR-0016 §1 already
  accepted that declarations are trusted, and the harm was bounded: an
  under-declared tool slipped past the gate more easily. Now it also *wins
  selection* against an honestly-declared peer, so a declaration that understates
  risk is rewarded twice over. Nothing mechanical detects it — verifying a
  declaration would need the per-call reach #57 defers, and even that reports
  after the fact. It is filed rather than mitigated, and it is an argument for
  treating declaration provenance as a real question once tools arrive from
  third parties rather than from this repository.
- **A capability-name collision now resolves silently instead of stalling.** Two
  integrations using one flat string for genuinely different operations
  (ADR-0016 §5's deferred namespacing) previously produced
  `AMBIGUOUS_CAPABILITY`; they now produce a running tool. The direction of the
  error is the conservative one — the ordering picks the less severe
  declaration, so a collision resolves toward the tool that discloses less and
  risks less — but it is still the wrong tool, and it is the strongest argument
  yet for namespacing.
- **Selection stays upstream of the gate and the gate is unchanged.** ADR-0037
  §2's decide → record → read back → claim order, §3's read-back and identity
  check, §4's parking and `resume`, §5's one-commit denial and §6's entry rule
  are all untouched. The selection stage still hands the policy exactly one
  declaration, and still calls it exactly once per step.
- **"Informed by `permissions`" is discharged without a call, and that is a
  deliberate narrowing of what the phrase could have meant.** Probing
  `ActionPolicy.decide` on each candidate and preferring the least restrictive
  outcome was the literal reading and is rejected: it computes rulings nobody
  records, and — the deciding objection — it makes tool choice a function of the
  user's threshold configuration, so lowering a threshold silently re-weights
  which axis of the ordering dominates. Agreement about severity gets the same
  guarantee in the dominated case, which is the case that matters, and gets it
  from a contract clause rather than from a call.
- **The user is asked at most once per step, and never about tools.** The
  question they answer is the permission question, which shows the chosen
  declaration by name and description. The cost is that a user who would have
  preferred the other candidate can only refuse, not redirect; redirection is
  the durable preference §7 defers.
- **A tie is still a stall, and it is now the *only* stall.** Where the user has
  expressed no preference between two indistinguishable tools, the step stays
  `PENDING` exactly as before. `StepDisposition` naming the tied candidates is
  what makes that recoverable — a surface can ask once, ever, and record the
  answer — but the surface and the record are both deferred, so on the day this
  lands the recovery is an operator editing the composition root.
- **`StepRunner` gains one constructor argument and no collaborator.** The
  preference sequence joins `confirmation_ttl` as configuration the composition
  root supplies; no Protocol is injected for it, and there is nothing to fake.
- **Revisit when** the first real MCP registry arrives and the tie residue can be
  measured; when parameter-schema enforcement lands and §7's eligibility clause
  is exercised; when standing grants (ADR-0021 §6) give a durable preference
  somewhere to live; or if capability-name collisions become real, which §7 and
  the bullets above both make more likely than ADR-0016 §7 assumed.
