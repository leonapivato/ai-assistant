# 145. Arguments are checked against the declared schema before anyone is asked, and one dialect is read

- Status: Proposed
- Date: 2026-08-13
- Decides: what ADR-0016 §7 defers — "parameter validation against
  `parameters_schema`" — restated and re-deferred by ADR-0029 §7 and declined in
  passing by ADR-0037 §1. It settles the runtime dependency both deferrals name
  as the blocker, under ADR-0003's process.
- Records for ratification: dated notes on ADR-0016, ADR-0029 and ADR-0037,
  whose exact forms are in §12. No `Status` line moves, for the reason ADR-0029
  §9 gives.
- Does **not** discharge ADR-0017 §3's "per-call gating that runs before
  transmission" condition, and §11 says why the adjacency is not a discharge.

## Context

`ToolDefinition.parameters_schema` has been carried since ADR-0016 §4 and read
by nothing. The field's own `Field(description=...)` in
`src/ai_assistant/core/types.py` says so — "carried, not yet enforced" — and so
does every consumer that would have used it: `StepRunner.run`'s docstring in
`src/ai_assistant/orchestration/runner.py` records that the parameters the
policy rules on are "unvalidated against the tool's `parameters_schema`", and
`src/ai_assistant/tools/builtin.py`'s module docstring records that "each
callable validates its own inputs and raises on a bad argument".

Three ADRs deferred it, each for the same reason and each narrowing the
question:

- **ADR-0016 §7** — "validating a `PlanStep`'s parameters against it at
  selection time needs a JSON Schema implementation, which is a runtime
  dependency decision, and has no consumer until invocation exists."
- **ADR-0029 §7** — "That is still true and it is not this ADR's decision to
  make — adding a dependency is ADR-0003's process, and choosing between
  implementations is a trade-off about vendoring, draft support and error
  reporting that has nothing to do with invocation. Its absence is bounded
  rather than silent: an unacceptable argument reaches the tool and comes back
  as `INVALID_REQUEST` (§3), which is not retryable, so the failure is loud and
  terminal instead of being caught early."
- **ADR-0037 §1** — "**Rejected: validating `step.parameters` against
  `tool.parameters_schema`.** ADR-0016 §7 defers it explicitly, pending a JSON
  Schema runtime dependency. The parameters flow into the `ActionRequest`
  unvalidated, exactly as they flow into the plan."

Both blockers have expired. Invocation exists (ADR-0029, implemented), so the
consumer ADR-0016 §7 was waiting for is here; and the dependency question is
what this ADR is dispatched to answer. ADR-0037's rejection is conditional on
ADR-0016 §7's deferral by its own words, so discharging that deferral is what
ADR-0037 was waiting for rather than something it ruled against.

**What "loud and terminal" costs, concretely.** ADR-0029 §7's bound is honest
about the failure being *reported*; it is not a claim about when. Follow the
order `StepRunner.run` actually runs — capability resolved, `find` returns one
candidate, `ActionRequest` built, `ActionPolicy.decide`, the decision recorded
in the append-only trail, the step claimed `RUNNING`, then `invoke`. A payload
the tool cannot accept survives every one of those. So the system asks the user
to approve an action that could never have happened, writes a permission
decision about it into a Tier 1 durable trail, claims the step, and only then
learns the arguments were the wrong shape. Leg 12's exit test is *"the user was
asked exactly once, at the moment it mattered"* (`docs/roadmap.md`, item 12); a
prompt for an unperformable call is a moment that did not matter.

It is worse than ADR-0029 §7 predicts in one detail. The bound assumes the tool
answers `INVALID_REQUEST`; today's two tools raise `ValueError` from their
hand-written argument checks in `src/ai_assistant/tools/builtin.py`, which
`run_bound_call` classifies `INTERNAL` (ADR-0029 §3) — "the tool implementation
is broken", recorded of a tool that was working correctly.

**The arguments arrive unseen.** `ModelBackedPlanner` in
`src/ai_assistant/planning/planner.py` checks only that a step's `parameters`
decode as a JSON object, and the planner's prompt never shows the model any
tool's schema — a step names a *capability*, and no tool is bound to it until
selection. So a mismatch is the expected case rather than an exotic one, and
nothing in the pipeline is positioned to notice it before the tool does.

**Leg 12 is what makes this urgent rather than tidy.** Roadmap item 12 is
MCP-shaped tool breadth: definitions built from schemas authored elsewhere, by
servers this repository does not control, in whatever dialect their authors
chose. Two ratified rules meet there. ADR-0016 §1 requires every safety-relevant
property to be *declared, not inferred*, and a tool that under-declares "does
not load". ADR-0004 §2 and ADR-0017 forbid egress outside a designated seam that
does not exist — and a JSON Schema evaluator handed a remote `$ref` will fetch
it if the library is configured to, which would be an unauthorised network read
performed by a validator, against a document a third party can change between
one call and the next.

This adds `core` surface — a member on an existing `core` enum, one new `core`
type and one `core` function — so it is a substantive contract ADR (golden
rule 5, ADR-0015 §5) and merges as its own PR ahead of any implementation.

## Decision

We will enforce the declared schema **where the arguments first meet a tool**,
which is before the permission ruling and before anything durable is written;
refuse a schema the repository cannot read rather than reinterpreting it; and
adopt `jsonschema` as the implementation, confined to `core`.

### 1. The check runs before the ruling, because the ruling is what it protects

`ToolDefinition.parameters_schema` and `ActionRequest.parameters` first sit on
one object at `ActionRequest`. That is not a coincidence of layout: an
`ActionRequest` **is** the pairing of a chosen tool with the arguments proposed
for it, and it is the value `ActionPolicy.decide` rules on, the value
`PermissionDecision.from_request` pins by digest, and the value the user is
shown a `reason` about. Everything downstream of it is either a ruling on those
arguments or an execution of them.

> **Normative.** An `ActionRequest` whose `parameters` do not satisfy its
> `tool.parameters_schema` is refused at construction. This holds for every
> validated construction, with no exception for a request built for a
> confirmation resume, for a replay, or for a test.

> **Normative.** No component may obtain an `ActionRequest` by a route that
> bypasses validation — `model_construct`, or mutation after construction — and
> a component holding a request it did not build through validation revalidates
> it before ruling on it, recording it or acting on it.

**The bypass is inside the threat model, and the clauses above are scoped so
they do not claim otherwise.** ADR-0029 §2 is explicit that `frozen=True` does
not survive a `__dict__` write and that "`model_construct` bypasses every
validator", and it answers that not by asserting a stronger invariant but by
re-running the check at the seam. The same division holds here, in ADR-0029
§2's own words: the validator "catches the honest mistake at the point it is
made", and the seam is what holds "against a deliberate one". A request built by
a bypass is still refused before the callable — ADR-0029 §2's step 1 revalidates
the whole call and therefore re-runs this validator — but it is refused *there*,
having already cost the prompt and the claim. That is the residue, and it is the
same residue every other invariant on these types carries rather than a new one
this ADR introduces.

**Before the ruling, not after it, and the ordering is the substance of this
clause.** Four things happen in `StepRunner.run` between the request and the
call, and putting the check after any of them spends something that cannot be
taken back:

- **The user is asked.** A `CONFIRM` on a malformed call trains a user to
  approve things that then fail for reasons the prompt never mentioned. ADR-0016
  §5 names that failure mode in its own terms — a permission system that
  "trains its user to approve everything" — and leg 12's exit test is a claim
  about being asked *once, when it mattered*.
- **The trail is written.** ADR-0021 §4 makes the audit trail append-only and
  Tier 1. A ruling on a request nothing could perform is a permanent record of a
  decision about a non-event.
- **The step is claimed.** ADR-0014 §4 requires the `→ RUNNING` commit before
  the tool is invoked, so a refusal after it strands durable state that has to be
  moved somewhere — the exact cost ADR-0029 §8 spends a bullet avoiding for
  `ToolBindingError`.
- **The digest is taken.** `PermissionDecision.parameters_digest` binds the
  arguments *as given*. Validating afterwards can only report on what was already
  authorised.

Checking at construction reaches all four together, because a request that was
never built cannot be ruled on, recorded, claimed or digested — and it reaches
them without anything being sequenced correctly, which is the property a rule
placed later would not have. What it does not do is reach them for a caller that
declined to build the request through validation at all; §2's clause on the
selection stage is the obligation that covers that caller, and the paragraph
above is what happens when it is broken.

**ADR-0016 §7 said "at selection time", and the request is what selection
produces.** A `PlanStep` names a capability, not a tool (ADR-0014 §2), so there
is no schema to check a step's parameters against until a tool is bound to them.
Selection is the moment that binding happens, and `ActionRequest` is the value
it produces. This lands the check where §7 pointed, at the object that exists
there rather than the one that does not.

**`invoke` gains no new check, and that is a result rather than an omission.**
ADR-0029 §2's step 1 revalidates the whole call through ADR-0018 §4's
`model_dump()`/`model_validate()` idiom, which reconstructs the nested
`ActionRequest` and therefore re-runs this validator; its step 2 then proves the
carried definition equal to the registry's original, so the schema step 1 ran
against is the trusted one. A call that reaches the callable with arguments its
tool's schema rejects is unreachable without defeating both, and the two ways to
try — `model_construct`, or a `__dict__` write — are already refused by §2's
existing checks, the second because `parameters_digest` is a property computed
from the mapping and `authorises` compares it.

### 2. The semantics live in `core`, in one implementation, because two stages need them and neither may import the other

> **Normative.** The rule that decides whether a parameter mapping satisfies a
> schema is implemented once, in `core`, and exposed as a function every
> consumer calls. No subsystem implements, re-implements, or configures its own
> schema evaluation, and no consumer may substitute its own evaluator for the
> `core` one.

This is ADR-0016 §2's argument, applied to the same three-part test it
established for `RiskLevel`'s ordering and ADR-0029 §2 re-applied to
`authorises`. The computation is **(a)** computable from the two values alone —
the request carries both the schema and the arguments; **(b)** independent of
policy, configuration, context and clock, which §5 through §9 are what make
true, since a configurable dialect, an asserted `format` or a retrievable
reference would each break it; and **(c)** the same answer for every consumer.

**No subsystem can own it, for ADR-0016 §2's reason verbatim.** `orchestration`
needs the answer to decide whether to request a ruling at all; `tools` needs the
same rule to hold at the seam. Golden rule 1 forbids either importing the other,
so an implementation in one of them is an implementation duplicated in both —
two copies of a safety-relevant predicate, free to disagree, with nothing that
fails when they do.

**The shape.** `core` gains a function returning the violations, and a frozen
type to carry one:

```python
class ParameterViolation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str            # schema-named locations and array indices only (§8)
    keyword: str         # the schema keyword that failed
    schema_value: FrozenJsonValue    # the schema's own value for that keyword

def parameter_violations(
    schema: Mapping[str, FrozenJson], parameters: Mapping[str, FrozenJson], /
) -> tuple[ParameterViolation, ...]: ...
```

These are shapes rather than implementations, as every contract ADR in this
repository has written them (ADR-0029 §3); §13 says what the implementation PR
owes.

**Both a function and a validator, and each is doing a different job.**

> **Normative.** The stage that binds a tool to a step's arguments computes the
> violations before it requests a permission ruling, and requests no ruling when
> there are any. The validator in §1 is the backstop for a caller that does not,
> never a substitute for this obligation.

The function is the ordinary path: the selection stage calls it before
constructing the request, so it gets a structured answer and a disposition (§4)
rather than an exception it would have to classify — and, because it is an
obligation on the stage rather than a consequence of a type, the pre-ruling
boundary holds even for a request the stage obtained some other way. The
validator is what makes §1's refusal true of every request built through
validation rather than of the ones a caller remembered to check. ADR-0029 §2
took the same two-placement shape and stated the principle: a rule an executor
can forget, "in a codebase whose ADR-0026 Context documents the same convention
being remembered at one site and missed one file over".

**`ParameterViolation` carries no field that could hold an argument value**, and
that is the enforcement of §8 rather than a description of it. `path` is
composed under §8's rule, `keyword` comes from the schema, and `schema_value` is
the schema's own value. A renderer that wanted to interpolate the instance would
have to obtain it from somewhere other than the violation.

### 3. A mismatch is not a `ToolFailure`, and `INVALID_REQUEST` keeps a narrower meaning

> **Normative.** A parameter-schema mismatch never reaches a tool's callable and
> never produces a `ToolResult`. `ToolFailureKind.INVALID_REQUEST` is not the
> vocabulary for it, and no seam synthesises an `INVALID_REQUEST` failure for a
> violation of a declared schema.

The invariant is about the callable and the result rather than about `invoke`,
because §1 leaves one path into `invoke` open: a request built by a bypass
reaches the seam and is refused by ADR-0029 §2's step 1 revalidation, before the
callable and without a result. §2's obligation on the selection stage is what
keeps the ordinary path out of the seam entirely.

The three checks ADR-0029 §2 puts in `invoke` raise `ToolBindingError` because
they answer *"is this the authorised call?"*, and a substitution fault must not
be recordable as an ordinary result. A schema mismatch is not that question: the
arguments **are** the ones that would have been authorised; they are the wrong
shape for the tool. So on the ordinary path it is neither a `ToolBindingError`
nor a `ToolFailure` — it is a value that does not get built, reported to its
caller in-process, before any of the machinery that produces either exists.

**`ToolBindingError` is retained, unchanged, for the bypass path, and the two
are not the same event.** A request that arrives at the seam having skipped
validation fails ADR-0029 §2's step 1, and that step's rule is already written:
"a revalidation failure carrying the underlying `ValidationError` as its cause".
Nothing here alters it, and nothing here should — by the time a request reaches
`invoke` unvalidated, the fact worth recording is not *which* validator it
failed but that the thing about to run was not built the way anything is
entitled to build it, which is exactly what §2's error means. So the two
refusals are distinguished by where they happen rather than by a new error type:
the selection stage's is a disposition (§4), the seam's is the
`ToolBindingError` ADR-0029 §2 already specifies, and ADR-0029 §8's handling of
it — committed `RUNNING → FAILED`, never retried — applies as written.

**What ADR-0029 §7's bound becomes.** It is discharged in its premise rather
than contradicted in its conclusion. `INVALID_REQUEST` keeps its ratified
meaning and its `retryable = False` — it remains what a tool reports for
arguments it will not accept **for reasons its schema does not express**: an
identifier that does not resolve, a recipient the upstream refuses, a
combination of well-typed values that is not a legal request. What stops arriving
through it is the class a declared schema can decide. The kind is not narrowed
as a contract; the population reaching it is.

**Retryability is unchanged in both directions.** `INVALID_REQUEST` stays
non-retryable, and the new refusal is not retryable either, for a stronger
reason than a flag: there is no `ToolResult` to retry from, and ADR-0029 §8's
rule — "retry is scheduled only from a `ToolResult`, never from an exception" —
therefore covers it without amendment. Re-submitting identical arguments against
an unchanged schema cannot start passing; what unblocks the step is different
arguments, which is a different request.

### 4. `Disposition` gains `INVALID_PARAMETERS`, and the step stays `PENDING`

> **Normative.** `Disposition` gains one member, `INVALID_PARAMETERS`, returned
> when the selected tool's schema rejects the step's parameters. It commits
> nothing: no ruling is requested, no audit record is written, no claim is made,
> and the step stays `PENDING`. It is terminal for the turn that met it and for
> nothing beyond it.

This is `AMBIGUOUS_CAPABILITY`'s shape, and ADR-0037 §1's argument for that
shape transfers without adjustment: "No `SkipReason` is true of it" —
`NO_CAPABLE_TOOL` is a lie when the tool is capable and the arguments are not,
and `UNMET_DEPENDENCY` and `SUPERSEDED` describe other things — so "writing a
falsehood into durable state to make a return value tidier is the failure
ADR-0014 §4's `_LEGAL_SKIP_REASONS` table exists to prevent". `PENDING` is
already the truth: nothing has happened to this step, and it is the state a
re-plan with corrected arguments can still run it from.

**It is not the `FAILED` member ADR-0037 refused.** That refusal is about a
disposition asserting a step *failed*, which is durable state the runner does not
commit; `INVALID_PARAMETERS` asserts nothing about the step's status and writes
nothing. (The refusal is cited as "ADR-0037 §8" by `Disposition`'s docstring in
`src/ai_assistant/core/types.py` and by ADR-0084 §4, and ADR-0037 has six
sections. The argument this clause relies on is ADR-0037 §1's, quoted above,
which is in the document; the stale citation is filed rather than repaired here.)

**No ADR-0014 change, and that is a boundary this ADR keeps.** No `SkipReason`
is added, the transition graph is untouched, and no state is written — so
nothing here is a change to a contract this lane does not own.

**Adding an enum member is additive on the wire.** `Disposition`'s values are
`StrEnum` strings a client reads (ADR-0084 §4), and a client that switches
exhaustively meets a value it does not know. The exposure is bounded by
deployment rather than by a compatibility rule: the hub is loopback-only and
ships with its client from one install, so the exhaustive readers are in this
repository. §13 makes finding them the implementation lane's obligation.

### 5. One dialect is read: 2020-12, assumed when unstated, and any other refused

> **Normative.** A `parameters_schema` is read as JSON Schema draft 2020-12 and
> as nothing else. A schema carrying no `$schema` is read as 2020-12; a schema
> whose `$schema` names any other dialect is refused under §6. No configuration,
> setting or per-tool option selects a dialect.

**Reinterpreting a schema in a dialect its author did not write it in fails
open, which is why refusal is the answer.** Draft-07 and 2020-12 disagree in
ways that change what is accepted, and 2020-12 ignores keywords it does not
know: a draft-07 schema whose array bound is `additionalItems` has that bound
*silently dropped* when read as 2020-12, and the tool receives a payload the
author believed was refused. Some of the disagreement is caught — draft-07's
tuple form `"items": [...]` is rejected outright by 2020-12's schema check,
verified against `jsonschema` 4.26.0 on Python 3.14.6 — but "some" is the wrong
guarantee for a rule whose failures are permissive.

**One dialect rather than a supported set, and the cost is named.** Supporting
several would mean the same arguments are accepted or refused according to a
string inside the schema, and a reviewer reading a definition would have to know
which dialect's semantics applied before knowing what the definition allows. The
cost is that a discovered tool explicitly declaring draft-07 does not load. That
cost is small where it matters most: MCP's tool schemas are draft 2020-12, and
schemas in the wild overwhelmingly omit `$schema`, which this clause reads as
2020-12.

**The dialect is this system's, not the remote's.** An adapter that meets a
schema in another dialect may translate it and declare the translation — a
visible, reviewable act producing a definition that says what it means — or it
may refuse the tool (§9). What it may not do is hand over a document to be read
under semantics its author did not use.

**One form of the dialect is out of reach, and the narrowing is stated rather
than left to be discovered.** Draft 2020-12 admits a *boolean* schema — `true`
accepts every instance, `false` accepts none — and `ToolDefinition.
parameters_schema` is a `FrozenJsonMapping` by ADR-0016 §4's ratified
declaration, so the field cannot hold one. This ADR does not widen that field:
changing a ratified type's declaration is a change to ADR-0016's decision, not a
deferral of it being taken up.

> **Normative.** A `parameters_schema` is an object schema. The boolean schema
> forms draft 2020-12 admits are outside what the field can hold, and a
> component building a definition from a description that uses one declares the
> object form with the same meaning — `{}` for `true` — or refuses the tool
> under §9. Neither boolean is read as a schema, and neither is silently
> discarded.

The narrowing is of the schema *language*, not of the *dialect*: every schema
this field can hold is read as 2020-12 and nothing about keyword semantics
changes. It costs nothing expressible, because `true` is `{}` — which §9 already
rules is a declaration of no constraint — and `false` is a tool that refuses
every call, which is a definition that could never be used and is better
declined at the adapter than loaded. What the narrowing buys is that §6's
construction check and §2's function have one input shape rather than two, in
`core`, on a field whose type was fixed before this decision existed.

**A schema that no object can satisfy is not detected**, and §6's root-type
clause is deliberately syntactic. `{"not": {}}` is the object spelling of
`false`, and deciding satisfiability in general is not something a construction
check can do. So a definition can load and refuse every call; it fails the same
way an over-strict schema does, visibly, on the first call, at the selection
stage rather than at the tool.

### 6. A schema that cannot be read is refused at construction, so no later stage meets one

> **Normative.** `ToolDefinition` construction refuses a `parameters_schema`
> that is not a valid draft 2020-12 schema, that declares a `$schema` other than
> draft 2020-12, that breaches the reference model below, or whose root
> carries a root `type` keyword that does not admit `object`. That last is a
> syntactic check on the root `type` keyword alone: a schema that excludes every
> object by some other construction is not refused here.

> **Normative.** Schema validity is a `ToolDefinition` construction check and
> nothing else. It runs wherever a `ToolDefinition` is constructed, including
> every defensive revalidation and detachment already required of a registry, of
> a request and at the seam, and no stage adds a schema check of its own.
> Evaluating a call's arguments never re-establishes the validity of the schema
> it evaluates against.

**The reference model is stated rather than left to "does it need retrieval",
because that question is not decidable from the syntax alone.** An external
`$ref` is a perfectly valid 2020-12 schema, so meta-validation accepts it and
the failure surfaces only when something tries to resolve it — at call time,
which is precisely what this section promises never happens. So the permitted
set is fixed by construction and checked by resolution:

> **Normative.** In a `parameters_schema`, every `$ref` value begins with `#`
> and resolves within the schema document itself; `$id` appears at the root or
> not at all; and `$dynamicRef` and `$dynamicAnchor` do not appear. `$anchor` is
> permitted. Construction resolves every reference against a registry containing
> that one document and nothing else, and refuses the schema when any reference
> does not resolve **or when the reference graph contains a cycle**.

Each exclusion is a case where a `#`-prefixed reference stops meaning
"somewhere in this document": a subschema `$id` re-bases resolution, so a
reference that reads local resolves elsewhere; and a dynamic reference is
resolved against the dynamic scope at evaluation time, so what it points at is
not a property of the document a reviewer is reading. Neither is needed to
describe a tool's arguments, and refusing both keeps "the schema is
self-contained" a fact a reader can check by looking at it. Resolving at
construction rather than merely pattern-matching is what makes a dangling
fragment — `#/$defs/Absent` — a definition that does not load instead of a call
that fails.

**The cycle clause is the one that stops a schema from being a weapon, and it is
why the whole reference model is worth stating.** `{"$ref": "#"}` satisfies every
other condition above — the reference is same-document, it resolves, there is no
`$id` and no dynamic keyword, and it is a valid 2020-12 schema — and evaluating
any instance against it recurses until the interpreter gives up. A cycle through
`$defs` does the same. Under leg 12 that schema arrives from a server this
repository does not control, so the shape of the attack is: publish a tool, have
it discovered, and every call that reaches validation exhausts the stack. §7's
fail-closed clause means the *outcome* is still a refusal rather than a pass —
`RecursionError` is an `Exception` — but a refusal reached by exhausting the
stack is not the "report the violations" behaviour §2 promises, and it is
reached inside `core`, on a path every tool call takes.

**Refusing every cycle rather than only the divergent ones, and the cost is
real.** A cycle that is *instance-consuming* — `#/$defs/node` reached through a
`properties` step — terminates, because the instance is finite; only a cycle
reachable without consuming any instance diverges. Distinguishing them means
classifying every keyword as consuming or not and getting that classification
right, in the check whose whole job is to be trustworthy about documents from
untrusted servers. A plain reachability walk over `$ref` targets is decidable,
total, and has no subtle case to get wrong, and it is chosen for that. The cost
is that a genuinely recursive argument — a tree, a nested filter expression —
cannot be declared, and an adapter meeting one bounds the nesting explicitly or
refuses the tool (§9). Bounding the depth is arguably the better declaration
anyway, since an unbounded-depth argument is an unbounded payload. Revisit if a
tool worth having turns out to need one.

**What this does not bound is evaluation *cost*.** An acyclic schema can still
be expensive, and a deeply nested instance recurses on its own way in — but the
parameters were already deep-frozen by `_freeze_json` on the way to becoming a
`FrozenJsonMapping`, which walks the same structure, so that limit predates this
decision rather than arriving with it. A cost budget for pathological-but-
terminating schemas is a separate rule with a constant nobody can calibrate yet,
and §14 scopes it out with an issue rather than inventing one here.

**One check on the type, inherited by every stage that rebuilds one.** The
repository already revalidates a definition wherever it could have been tampered
with: ADR-0018 §4 requires that "what a registry stores must be valid and
detached"; `_detached_tool` in `src/ai_assistant/core/types.py` rebuilds the
definition through `ToolDefinition.model_validate(...)` as an `ActionRequest` is
built; and ADR-0029 §2's step 1 does the same for the whole call at the seam.
Putting the check on construction places it at all of them at once — no
`ToolRegistrationError` case is added, and there is no per-stage rule to keep in
step. That is also what closes the corruption route: a definition mutated
through `object.__setattr__` into carrying a remote `$ref` is refused by the
revalidation those clauses already mandate, rather than surviving to evaluation.
The check having *one* definition — on the type — is what makes that true
without any of those stages knowing about schemas.

Because a `ToolDefinition` in hand was built by some construction, §1's
validator and §2's function may assume a readable schema: they report violations
in the arguments, never a defect in the document they are reading.

**Fail-closed, in ADR-0016 §1's direction.** That section's rule is that "a tool
that does not declare its reach does not load", because a construction error is
better than a silent under-protection. A schema nobody can evaluate is a
declaration nobody can check, and the same answer applies.

**The root-`type` clause catches a real authoring mistake cheaply, and it is
deliberately not a satisfiability rule.** `ActionRequest.parameters` is a
mapping, so a schema whose root says `"type": "string"` would load as a
definition no call could ever satisfy; pasting the wrong schema is exactly the
error an MCP adapter will make, and one keyword lookup says so at the moment the
definition is built. What the clause does not do is decide whether *some* object
satisfies the schema, which is not something a construction check can answer in
general — so `{"not": {}}`, the object spelling of `false` (§5), loads. The two
halves are complementary rather than in tension: the cheap syntactic case is
refused because it is cheap and common, and the general case is left to fail
visibly on the first call, at the selection stage rather than at the tool.

**One durable consequence, stated rather than discovered.** A stored
`PermissionDecision` embeds its `ToolDefinition` by value (ADR-0021 §1) and is
revalidated when read back from the trail, so a record whose tool carries a
schema this clause refuses would become unreadable. No such record can exist in
the corpus this ADR is written against: the two shipped definitions in
`src/ai_assistant/tools/builtin.py` declare plain object schemas with no
`$schema`. A future change of dialect would be a migration question, and this
ADR neither creates a migration mechanism nor claims one is unnecessary — §13
requires the check that today's definitions load, and §14 scopes the migration
out.

### 7. Evaluation performs no I/O and modifies nothing

> **Normative.** No schema evaluation performs any I/O. The evaluator is
> constructed with no capability to retrieve a resource, so a reference outside
> the schema document cannot be fetched even where §6's construction check
> failed to refuse it.

**A validator that fetches is an egress.** ADR-0004 §2 as amended by ADR-0017 §1
permits off-device transmission only from `models/` or a designated `tools/`
seam, and ADR-0017 §2 leaves that seam **undesignated** — so a `$ref` retrieved
over the network from `core` is an unauthorised egress performed by the least
expected component in the system. It is also a correctness failure independently
of the egress: what a tool call is allowed to contain would depend on a document
a third party can change between one call and the next, which breaks §2's
clause (b) outright.

The default of the library §10 adopts is refusal rather than retrieval — a
remote `$ref` raises rather than fetching, verified against `jsonschema` 4.26.0
on Python 3.14.6 — so this clause is satisfied by not supplying a retriever, and
the construction check in §6 is the belt over that brace rather than the only
guard.

> **Normative.** Validation never modifies the parameters: no schema `default`
> is applied, no value is coerced, and the mapping validated is the same
> canonical JSON form `ActionRequest.parameters_digest` is taken over.

Filling a default would change the arguments after the caller chose them and
before the digest binds them, so the user would authorise a payload nobody
composed. Validating a different form from the one digested would let a value
pass in one shape and travel in another, which is the substitution ADR-0029 §2
exists to prevent, reached through the validator instead of through the seam.

> **Normative.** A schema evaluation that raises rather than returning
> violations refuses the request. No evaluation failure is ever read as a pass.

### 8. No message renders any part of the arguments

> **Normative.** No message, log record or durable value this decision produces
> renders any part of the parameters — neither a value nor a key. A violation is
> described by the schema-side facts alone: the failing keyword, the schema's
> own value for it, and a path composed of array indices and property names the
> schema itself names. Where the offending location is a key the schema does not
> name, the path elides it rather than reproducing it.

**This is the sharpest hazard in the decision, and it is not hypothetical.** The
reference implementation interpolates the instance into its own message text.
Verified against `jsonschema` 4.26.0 on Python 3.14.6, a schema requiring an
integer, given an object carrying an address and an unexpected key, produces:

```text
'alice@example.com' is not of type 'integer'
Additional properties are not allowed ('X-Secret' was unexpected)
```

The first reproduces an argument value, the second an argument key. Tool
parameters are where recipients, subject lines and free text live, so both are
Tier 0/1 candidates landing in a Tier 2 log. ADR-0029 §3 already ruled this
exact class for the seam's own synthesised message — it "names the exception's
type and the tool's id; it does not interpolate `str(exc)`" — and recorded that
nothing downstream catches it, because `core/logging.py` redacts by *key* and its
own docstring names an interpolated message as the leak it cannot see. A naive
`str(error)` here is that leak, once per malformed call, on a path that will run
constantly.

**Keys are elided as well as values, and the reason is that a key can be data.**
A mapping the schema does not describe can be keyed by an address or an
identifier. The accepted cost is a thinner diagnostic: an
`additionalProperties` violation says *where* and *which keyword*, not *which
key*. That is ADR-0029 §3's trade, taken for the same reason — "the alternative
is a Tier 1 disclosure into a Tier 2 store on the failure path of every tool
nobody thought about".

**Correction does not need the value echoed back.** The producer of the
arguments already holds them; what it lacks is the constraint it missed, which
the keyword, the schema's value and the location supply exactly. A schema is
Tier 2 configuration authored by the tool's provider, so schema-side text is
safe to render.

> **Normative.** Where several violations are found, all are reported, in a
> deterministic order, and any truncation is stated in what is reported rather
> than performed silently.

One violation at a time turns a correction into a sequence of round trips, each
paying for a re-plan; a silently truncated list makes a caller believe it has
fixed everything.

### 9. An absent schema declares no constraint, and no adapter may fake one

> **Normative.** An empty `parameters_schema` — the field's default — declares
> *no constraint*, and every parameter mapping satisfies it. It is not an error,
> it does not refuse the call, and it is not a claim that the arguments were
> checked.

Making a schema mandatory would be a change to ADR-0016 §1's decision about
which fields are required, in place, which ADR-0070 §1 does not permit and which
this ADR was not dispatched to make. It is also the wrong fail-closed lever:
what gates a call is the required reach and risk declaration, and refusing every
tool without a schema would remove tools rather than protect calls. What is left
is exactly today's behaviour for such a tool — the tool decides, and says so —
bounded and loud.

> **Normative.** A component building a `ToolDefinition` from a description it
> did not author may not substitute an empty `parameters_schema` for one it
> cannot express in the dialect §5 fixes. It declares the translated schema, or
> it refuses the tool.

Emptying a schema is a declaration that the tool constrains nothing, made on
behalf of an author who said otherwise — ADR-0016 §1's forgetful-integration
failure, committed deliberately by an adapter taking the easy path. This is the
clause that makes §5's refusal mean something for schemas the repository did not
write: the alternative to translating is dropping the tool, not silently
widening it.

### 10. `jsonschema`, adopted under ADR-0003, confined to `core`

> **Normative.** The implementation is the `jsonschema` package. It is imported
> only by `ai_assistant.core`, and an `import-linter` contract in
> `pyproject.toml` pins that confinement, in the form ADR-0125 §8 uses for
> `keyring` and the readers' contract uses for `icalendar`.

ADR-0003's dependency rule is that a runtime dependency is justified in the
change and a foundational one takes an ADR; this is the ADR, and the
justification is that no evaluator exists in the tree — `pydantic` emits JSON
Schema and does not validate against an arbitrary one — while three ADRs have
deferred a ratified field's enforcement pending exactly this choice.

**The Python 3.14 filter (#664) is checked and does not decide it.** All three
candidates clear it, measured at PyPI on 2026-08-13: `jsonschema` 4.26.0 is
`py3-none-any` with `requires-python >=3.10`, and its only compiled dependency
is `rpds-py` 2026.6.3, which publishes 115 wheels including 29 `cp314` builds
across manylinux x86_64/aarch64, macOS and Windows; `fastjsonschema` 2.22.1 is
pure Python; `jsonschema-rs` 0.49.9 publishes `cp314` wheels. Installing
`jsonschema` under `--only-binary=:all:` on Python 3.14.6 resolves and installs
five packages with no source build. The filter is a gate all three pass, so the
choice is made on merits.

**Why the reference implementation.**

- **Draft 2020-12 is complete, not partial.** §5 makes the dialect the contract,
  so partial support for it is a partial contract.
- **The errors are structured, and §2's type needs exactly what they carry.**
  Each error exposes the failing keyword, the schema's value for it, and the
  instance path as a sequence — the three schema-side facts §8 permits, available
  without parsing a rendered string. `iter_errors` yields all of them, which §8's
  report-them-all clause requires.
- **Its default is to refuse retrieval**, which is the default §7 needs; a
  library that fetched unless configured otherwise would put the no-I/O rule one
  configuration mistake away from an egress.
- **`format` is annotation-only by default**, which is what §2's clause (c)
  needs — asserted formats vary with the library's version and optional extras,
  so the same definition would accept different arguments on two installs.

**Rejected: `fastjsonschema`.** Its 2019-09/2020-12 support is partial, against
the one dialect §5 reads. It reports the first violation and stops, which §8's
report-them-all clause forbids. And it works by generating Python source from
the schema and executing it — a code-generation path over documents authored by
remote MCP servers, which is a category of exposure no throughput argument pays
for. Speed is not the constraint here: the schemas are a handful of fields and
the evaluations are one per step.

**Rejected: `jsonschema-rs`.** Faster and 2020-12-capable, and rejected on
stability and detail rather than capability. It is pre-1.0 with a moving API,
and §2 puts this rule in `core`, where the cost of an API break is paid by the
most shared module in the tree; its error detail is thinner than the reference
implementation's, which §8 turns into a hard requirement rather than a
preference; and a swap to it would have to re-establish §7's retrieval default
from scratch rather than inherit it. It stays the answer if evaluation ever shows
up in a profile.

**Rejected: hand-rolling a subset.** A subset of JSON Schema is a dialect this
repository invented, and §5's whole argument is that a schema must be read under
the semantics its author wrote it in. It would also be the component that has to
be *right* about documents from untrusted servers, written here rather than by
the ecosystem that maintains the specification's reference implementation.

**The confinement contract is what keeps the swap cheap.** One import site means
one place to change, and it is what mechanically enforces §2's "no subsystem
configures its own schema evaluation" — otherwise a subsystem could build a
validator with an asserted `format` or a retriever attached and pass review.

### 11. This does not discharge ADR-0017 §3's per-call gating condition

> **Normative.** Nothing in this ADR discharges any condition ADR-0017 §3 sets
> on designating the `tools/` egress seam, and in particular not "per-call
> gating that runs before transmission". Ratifying it authorises no egress.

The adjacency is close enough to be worth refusing explicitly. ADR-0017 §3's
condition is contrasted with "merely a declared ceiling (ADR-0016 §3)", and a
reader who knows the ceiling is ADR-0016 §3's tier tuples might read a per-call
check of the arguments as the thing that replaces it. It is not, and the
difference is what the check *decides*: this one decides whether the arguments
are the shape the tool declared. It rules on nobody's authority, resolves no
recipient, classifies no tier, and cannot refuse a call on safety grounds — a
perfectly well-formed payload addressed to an unauthorised recipient passes it
without comment. §3's condition asks for a *permission* decision on the actual
call, which is `permissions/`'s to make, on inputs #57 and #94 have to design
first.

What this does contribute is a precondition rather than a discharge: a per-call
analysis that reads arguments needs them to be the shape their schema declares
before reading them is meaningful, and #57's manifest is such an analysis. The
contribution is stated so that the designation ADR ADR-0017 §2 requires can cite
it as an input and not as a condition met.

**One thing it makes visible for #57.** This ADR does not inject keywords into a
schema it did not write, so a schema that omits `additionalProperties` permits
keys it never described, and those keys travel in an authorised payload. That is
the schema author's choice and this ADR keeps it; it is also a fact a payload
manifest has to account for, and naming it here saves #57 rediscovering it.

### 12. What ratification does to ADR-0016, ADR-0029 and ADR-0037

ADR-0017 §7 requires the operation performed on another ADR to be recorded
rather than inferred. The notes below are applied **in the same commit that
flips this ADR's `Status` to `Accepted`**, and not before: writing "discharged by
ADR-0145" onto another ADR while this one is `Proposed` is the state claim
ADR-0019 forbids, and it is the reason ADR-0029 §9 declined to make its own
edits. This ADR is ratified before it merges, so the merged tree carries both the
ratification and the notes, and no tree that anyone reads carries either alone.

**No `Status` line moves**, on ADR-0029 §9's reasoning: ADR-0001 reserves a
status update to an ADR that *changes* a past decision, and each of the three
deferred this question rather than deciding it. A later ADR taking a deferral up
is that deferral working as designed.

- **A dated note appended to ADR-0016's header, after the existing note:**

  `Note (<ratification date>): §7's **parameter-schema validation** deferral is
  discharged by ADR-0145, which settles the runtime dependency §7 names as the
  blocker (jsonschema, confined to core) and places the check at ActionRequest
  construction — §7 said "at selection time", and the request is what selection
  produces, since a PlanStep names a capability and no schema applies until a
  tool is bound. §4's parameters_schema is unchanged in what it carries and
  gains two constraints on what it may hold: draft 2020-12 only, and no
  reference requiring retrieval, both refused at ToolDefinition construction
  (ADR-0145 §5, §6). §1's no-defaults rule is untouched — the schema keeps its
  default and an empty schema declares no constraint (ADR-0145 §9). §7's
  remaining deferrals — per-call data reach (#57), ranking and selection (#241),
  persistence, enablement, namespacing, transacted cost — are unaffected and
  remain deferred.`

- **A dated note appended to ADR-0029's header, after the existing amendment
  notes:**

  `Note (<ratification date>): §7's **parameter validation against
  parameters_schema** bullet is discharged by ADR-0145. Its bound — "an
  unacceptable argument reaches the tool and comes back as INVALID_REQUEST (§3),
  which is not retryable" — describes what no longer happens for a violation a
  declared schema can decide: such a request is refused at construction, before
  the ruling and before the claim, and reaches no tool's callable and no
  ToolResult (ADR-0145 §1, §3).
  §3 is unchanged: INVALID_REQUEST keeps its meaning and its retryable=False for
  arguments a tool refuses for reasons its schema does not express, and no seam
  synthesises it for a schema violation. §2's three checks and their order are
  unchanged and invoke gains no fourth — step 1's revalidation re-runs the new
  ActionRequest validator and step 2 makes the schema it ran against the
  registry's own. §7's remaining scope-outs are unaffected.`

- **A dated note appended to ADR-0037's header, after `Date`:**

  `Note (<ratification date>): §1's "Rejected: validating step.parameters
  against tool.parameters_schema" is superseded in its premise by ADR-0145. That
  rejection is conditional by its own words — "ADR-0016 §7 defers it explicitly,
  pending a JSON Schema runtime dependency" — and ADR-0145 settles the
  dependency and discharges the deferral, so §1's following sentence, "The
  parameters flow into the ActionRequest unvalidated", no longer describes the
  system. StepRunner checks them against the selected tool's schema before
  requesting a ruling and returns the new Disposition.INVALID_PARAMETERS, which
  commits nothing and leaves the step PENDING — §1's AMBIGUOUS_CAPABILITY shape,
  reached by §1's own argument that no SkipReason is true of it. Everything else
  in §1 stands: find's one-candidate rule, the several-candidates refusal, and
  the absence of a ranking rule (#241).`

- **No other ADR is edited.** ADR-0021 §3 records that `ActionRequest.parameters`
  is carried and unread *by the policy*, which stays true — no rule in
  `ThresholdActionPolicy` consults them and none is added here. ADR-0014's graph
  and `SkipReason` set are untouched. ADR-0004 and ADR-0017 are read and not
  amended: §11 discharges nothing of theirs. The line is ADR-0029 §9's — whether a
  sentence in the other ADR would now read as false.

### 13. What the implementation PR owes

None of this is built here (ADR-0015 §5). `ParameterViolation` and
`Disposition.INVALID_PARAMETERS` are `core` types rather than a new Protocol, so
`CONTRIBUTING.md` → "Adding a Protocol" does not apply and no triad is owed; what
is owed is the evidence for the claims above that a signature does not show.

- **The placement, as a refusal**: an `ActionRequest` whose parameters violate
  its tool's schema is refused at construction, and the selection stage's
  obligation (§2) is shown to bite *before* `ActionPolicy.decide` is reached —
  asserted as no ruling requested, no audit record written, no claim committed,
  and the step still `PENDING`, not merely as an exception raised. Both halves
  are needed: a test that only asserts the construction refusal proves nothing
  about where in the pipeline the stage stopped.
- **The seam inherits it without a fourth check**: a call whose parameters are
  swapped through `__dict__` after construction is refused by ADR-0029 §2's
  existing checks with the tool never reached, and `invoke` grows no schema step.
- **`INVALID_REQUEST` is not synthesised for a violation** — a tool is still
  free to return it, and nothing in the seam produces it from a schema.
- **The dialect rules, in both directions** (§5, §6): a schema declaring
  draft-07 refused at construction; a schema with no `$schema` accepted and read
  as 2020-12; an invalid schema refused; a root `type` excluding `object`
  refused — **and `{"not": {}}` accepted**, which is what pins the clause as
  syntactic rather than as a satisfiability rule an implementation might try to
  generalise. And the fail-open case that motivates the dialect refusal, pinned
  as a *rejection* rather than argued: a draft-07 schema whose bound is
  `additionalItems` does not load, so it cannot be read permissively.
- **The reference model, as refusals** (§6): an external `$ref`, a non-root
  `$id`, a `$dynamicRef`, a *dangling* same-document fragment (`#/$defs/Absent`),
  a self-reference (`{"$ref": "#"}`) and a two-hop `$defs` cycle each refuse the
  definition at construction. The dangling case is what distinguishes resolving
  from pattern-matching; the two cycle cases are the ones that must be asserted
  as *construction* refusals and not merely as calls that fail, since a test that
  only checks the outcome would pass against an implementation that reaches it by
  exhausting the stack. A same-document `$ref` and an `$anchor` are accepted, so
  the model is shown to be usable and not merely restrictive.
- **No I/O, as a test that cannot pass by accident** (§7): separately from the
  construction refusal, an evaluator built by the `core` seam is shown to raise
  rather than retrieve when handed an external reference, so the belt is tested
  without the brace.
- **Nothing is modified** (§7): a schema declaring `default` for a missing
  property leaves the parameters unchanged, and the digest before and after
  validation is equal.
- **The message rule, as the thing that leaks if untested** (§8): the two
  verified strings above are the fixtures. A violation whose instance value is
  `alice@example.com` and an `additionalProperties` violation on a key named
  `X-Secret` must each be shown to produce a rendering, a log record and a
  `ParameterViolation` in which neither string appears. ADR-0029 §10 required the
  same test for the seam's `INTERNAL` message and for the same reason: nothing
  downstream redacts it, so an untested rule here is an unenforced one.
- **All violations, deterministically ordered**, and a truncation that states
  itself.
- **An empty schema accepts everything** (§9), including a parameter mapping with
  keys, and is distinguishable in the record from "checked and passed".
- **Today's definitions still load** (§6): `CURRENT_TIME` and `RECALL_MEMORY`
  construct, and a stored `PermissionDecision` carrying either round-trips out of
  the trail.
- **The confinement holds** (§10): `uv run lint-imports` fails when a subsystem
  imports `jsonschema`, which means the contract is written and exercised rather
  than assumed.
- **Every exhaustive reader of `Disposition` is found and extended** (§4) — in
  `interfaces/`, in `wire/`, and in any client rendering — rather than left to
  fail on an unknown value.

The hand-written argument checks in `src/ai_assistant/tools/builtin.py` become
redundant for what the schemas already express. Removing them is not required by
this ADR and is not forbidden by it; if the lane removes them it owes the
observation that today those checks raise `ValueError` and surface as `INTERNAL`,
so deleting them changes a recorded outcome and the tests that pin it.

### 14. Explicitly out of scope

- **Showing the planner the schemas.** The model composes arguments without
  seeing any tool's schema (Context), so enforcement on its own converts a late
  failure into an early stall. Closing the loop — putting the bound tool's schema
  in front of whatever composes the arguments, or feeding the violations back for
  a correction — is a `planning`/`orchestration` decision about prompts and
  re-planning, with its own cost, and it is filed rather than assumed. This ADR
  is worth ratifying without it because the ordering it fixes is right either
  way: nothing is asked, recorded or claimed on a call that cannot run.
- **Carrying the violations to a client.** `StepOutcome` tells a client the
  disposition; a field describing *why* is an additive wire change with its own
  Tier question about what may be rendered, and §8 would govern it. Filed.
- **Validating a tool's `output` against a declared schema.** `ToolDefinition`
  declares no output schema and ADR-0029 §3 makes `output` a `FrozenJsonValue`
  the tool is trusted for. Adding one is an ADR-0016 field change.
- **A cost budget for schema evaluation** (§6). The cycle refusal removes the
  divergent case; an acyclic schema that is merely expensive is bounded by
  nothing here, and a constant to bound it by is not calibratable before tool
  breadth exists. Filed.
- **A schema migration mechanism** (§6). If the supported dialect ever changes,
  stored decisions carrying the old one are a migration question this ADR does
  not answer and does not need to, since the corpus it lands on has none.
- **Per-call data reach and the payload manifest** (#57), **recipient
  authorisation** (#68), and every other ADR-0017 §3 condition (§11).
- **Ranking among several capable tools** (#241) — ADR-0037 §1's other refusal,
  which is a sibling lane's.

## Consequences

- **The user is not asked about a call that cannot run.** This is the whole of
  the change from a user's seat, and it is the half of leg 12's exit test that is
  a mechanism rather than an experience.
- **The Tier 1 audit trail stops accumulating rulings on non-events.** A
  permission decision is now made only about requests that could be performed.
- **A step with bad arguments stalls instead of failing loudly, and that is a
  real regression in legibility until the follow-up lands.** Today the call runs,
  the tool complains, and the step ends `FAILED` with a message. Under this
  decision it stays `PENDING` with a disposition, and unless something feeds the
  violations back, a re-plan may produce the same arguments again. The stall is
  the safe direction — nothing was disclosed, approved or claimed — and it is
  ADR-0037 §1's accepted shape for `AMBIGUOUS_CAPABILITY`, but it is friction,
  and §14's first bullet is what removes it.
- **New `core` surface: three names** — `ParameterViolation`,
  `parameter_violations`, and `Disposition.INVALID_PARAMETERS`. No Protocol
  changes, no triad, no new error type, and `ToolFailureKind` is untouched.
- **`core` gains a third-party runtime dependency**, and it is the most shared
  module in the tree. A break or an advisory in `jsonschema` now reaches
  everything rather than one subsystem. The mitigations are that it is the
  ecosystem's reference implementation, that it is pure Python over one compiled
  transitive package with 3.14 wheels, and that §10's confinement contract makes
  the import site singular and the swap mechanical. The honest statement is that
  this is a real widening accepted for a rule that two subsystems need and
  neither may own.
- **A tool the repository did not write may not load**, and that is the intended
  direction. A discovered schema in another dialect, or one reaching for a remote
  reference, is refused at construction with a legible reason rather than
  reinterpreted or silently emptied. Under leg 12's breadth this will happen, and
  §9's second clause is what stops an adapter making it go away.
- **A validator no longer says what was wrong in the way its library would.**
  §8's rule costs diagnostic detail on every violation, permanently, to close a
  leak that has no downstream catcher. The producer of the arguments still holds
  them, so the loss is to the log reader, not to the corrector.
- **`ToolFailureKind.INVALID_REQUEST` becomes rarer and more meaningful.** It
  stops being the channel for "wrong shape" and keeps being the channel for
  "well-formed and unacceptable", which is what a caller can actually act on
  differently.
- **Two hand-written argument checkers become redundant.** The builtins
  re-implement their own schemas in Python, and one test pins the Python against
  the schema by hand. That duplication is what a declared schema was for.
- **Revisit when** MCP discovery lands (does the dialect refusal in §5 turn out
  to reject servers that matter, and does §9's translate-or-refuse rule hold up
  in an adapter?), when the payload manifest #57 designs needs the arguments
  described rather than merely well-formed, or if evaluation cost ever appears in
  a profile — in which case §10's rejected alternatives are where to look, not
  §5's dialect.

### The strongest case against this decision

It puts a third-party parser in `core` in order to catch a mistake the system
could survive, and it does so before the thing that makes enforcement useful
exists. The failure it removes is real but bounded and self-announcing — a tool
rejects the arguments and the step fails — while the failure it introduces is
quiet: a step that stalls, in a pipeline whose argument producer has never been
shown a schema. Ratifying enforcement before closing that loop optimises the
half of the problem that was already visible.

Three things answer it and none of them is a claim that the concern is wrong.
The ordering is not improved by waiting: every turn until the loop closes asks a
user to approve calls that cannot run and writes decisions about them into an
append-only trail, and those are the two costs that are not recoverable. The
dependency question is the one thing three ADRs said had to be settled before
anything else could be, so settling it unblocks the correction loop rather than
competing with it. And the alternative placements were considered and are worse
in a way that would be expensive to undo: in `orchestration` the rule is
duplicated in `tools`, at the seam it arrives after the prompt and the claim, and
in neither case is it a rule that cannot be skipped.

What would change the verdict is evidence that violations are rare in practice —
if a planner that has never seen a schema nevertheless produces conforming
arguments almost always, the stall costs little and the whole mechanism earns
less than its dependency. That is measurable once tool breadth arrives, and
§14's first bullet is the change that would make it moot either way.
