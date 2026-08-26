# 196. A frozen JSON value is refused past a fixed depth ceiling, measured before it is walked

- Status: Proposed
- Date: 2026-08-26

## Context

`FrozenJson` is the widest shared type in `core`. Every subsystem that carries
structured data across a boundary holds one. Nine fields across `core/types.py`
declare it — `PlanStep.parameters`, `StepExecution.output`,
`StepTransition.output`, `ActionRequest.parameters`, `BoundEgressCall.parameters`,
`Confirmation.parameters`, `ToolResult.output`, `ToolDefinition.parameters_schema`
and `ParameterViolation.schema_value` — and three `core/protocols.py` methods take
a `FrozenJsonMapping` parameter, so `orchestration`, `tools`, `permissions` and
`testing` all construct one. What that type accepts is what every one of them
accepts.

Two functions implement it. `_deep_freeze` walks the value recursively, turning
mappings into `FrozenDict` and sequences into tuples; `_freeze_json` calls it and
then runs the real JSON encoder over the result. `_freeze_json` is the
`AfterValidator` on both `FrozenJsonValue` and `FrozenJsonMapping`, and it is the
only caller of `_deep_freeze` in the tree.

**What #1107 asked for.** ADR-0145 §6 and §14 filed it: `_deep_freeze` recurses
with no depth limit, so — in the issue's words — "a sufficiently deep payload
exhausts the interpreter stack on the way in, today, with no schema evaluation
involved". ADR-0145 declined to place the bound, for two reasons it recorded: a
check placed *after* the freeze fires after the recursion it exists to prevent,
and a bound at the freeze reaches every holder of the type, which is "a
different decision, with its own cross-subsystem blast radius, and not one to
make inside a schema-enforcement ADR". This is that decision.

**The premise does not survive measurement, and the correction is the reason
this ADR reads the way it does.** Measured on 2026-08-26 against `main` at
`c08fa53a`, with pydantic 2.13.4 / pydantic-core 2.46.4 and
`sys.getrecursionlimit()` at its default 1000, counting containers in
`_json_depth`'s vocabulary — a scalar is 0 and `{}` is 1:

| mechanism | deepest value it accepts |
| --- | --- |
| pydantic-core validating the recursive `FrozenJson` alias | 256 |
| pydantic-core serialising a model that holds one | 255 |
| `_deep_freeze` alone, called directly | 997 |
| `_thaw_json` alone, called directly | 994 |

`_deep_freeze` is reached only through `_freeze_json`, and `_freeze_json` is
reached only as the alias's `AfterValidator` — which pydantic-core runs *after*
the recursive alias itself has validated. So nothing deeper than 256 containers
ever reaches the recursive walk, and the walk survives 997. **The stack
exhaustion #1107 describes is not reachable through any construction path in
this repository.** What refuses a deep payload today is pydantic-core's own
recursion guard, and it is refusing for a reason that is not this one: it reports
`recursion_loop`, "Recursion error - cyclic reference detected", about a value
with no cycle in it.

**ADR-0145 §6's residual is empty too, and for a second reason.** §6 records "a
window: an instance deep enough that the freeze survives and the evaluation does
not". Evaluation descends the schema and the instance together, and ADR-0145 §6
bounds the schema at 64 containers, so evaluation cannot descend past 64 however
deep the instance is. Measured: a 64-container schema evaluated against a
256-container instance through `parameter_violations` returns cleanly. There is
no depth at which the freeze survives and the evaluation does not, because there
is no depth at which the evaluation goes deeper than 64.

**Which leaves a question worth deciding, on three grounds that are not the one
that was filed.**

- **The protection is upstream, incidental and unpinned.** `pyproject.toml`
  declares `pydantic>=2.13.4` with no upper bound, so the constant that decides
  what a `core` audit type accepts lives in a third-party Rust extension, is
  documented nowhere in this repository, is asserted by no test here, and is free
  to move on any dependency bump. This is a repository that pins the exact form
  of `json.dumps` (ADR-0021 §1) so that encodability is a measurement rather than
  a claim; resting the acceptance set of `FrozenJson` on an unpinned upstream
  number is the same mistake in the other direction.
- **At one depth the type accepts a value it cannot store.** A `PlanStep` is
  constructible with `parameters` 256 containers deep — validation accepts it,
  `_freeze_json` runs the encoder over it and passes — and `model_dump_json()` on
  the result then raises `PydanticSerializationError`, "Error serializing to JSON:
  ValueError: Circular reference detected (depth exceeded)". Construction stops at
  256 containers and serialisation at 255, and the container in between is a value
  the type says yes to and cannot write down. That is the "accepted, then
  unusable" shape ADR-0014 §2 exists to close and `_freeze_json` cites in its own
  docstring as its reason for running the real encoder — open here because the
  encoder it runs is not the one the model dumps through.
- **The refusal is illegible, and at one depth it is wrong.** A `ToolDefinition`
  whose `parameters_schema` nests 257 containers is refused with 1276 validation
  errors, of which exactly one is the `recursion_loop` and the first reported one
  reads "Input should be a valid string". At 256 containers it is refused with
  "tool has no JSON encoding, so it could not be stored", carrying
  `ValueError('Circular reference detected (depth exceeded)')` — a depth failure
  reported as an encoding failure about a value that encodes fine. A caller
  cannot tell "too deep" from "wrong type at some leaf" in either case.
- **Acceptance varies with a process-global.** The guard tracks the interpreter's
  recursion limit: at `sys.setrecursionlimit(200)` the deepest accepted value
  drops from 256 containers to 194. So the same payload is accepted in one
  process and refused in another, decided by a setting any dependency may change,
  for a type whose whole purpose is to be part of an audit record that is
  persisted, exported and revalidated (ADR-0018 §4).

So the question is not "how do we stop a crash" — nothing crashes. It is what
depth a shared `core` ingress accepts, whether that answer is ours or a
dependency's, and what it says when it refuses.

## Decision

### 1. A frozen JSON value nested past a fixed ceiling is refused at the front of its own validation

> **Normative.** A value validated as `FrozenJsonValue` or `FrozenJsonMapping`
> whose container nesting exceeds the ceiling of §3 is refused by raising
> `ValueError` with a message naming depth and the ceiling as the reason, and
> that refusal is reached **before any other validation of the value has run** —
> including the recursive `FrozenJson` alias's own — so that it holds whatever
> `sys.getrecursionlimit()` is set to.

> **Normative.** That refusal introduces no new exception type: it reaches a
> caller as the holder's ordinary construction refusal, exactly as the
> non-finite-float and no-JSON-encoding refusals in `_deep_freeze` and
> `_freeze_json` already do.

The placement is the whole point of putting it here rather than on a holder. The
property being enforced — "this value can be walked, encoded, stored, dumped and
revalidated" — is intrinsic to the value and not to who holds it, which is
ADR-0016 §2's test and the reason `_freeze_json`'s existing refusals sit where
they do. A per-holder bound would be the same rule written nine times, free to
disagree, with nothing that fails when it does.

**At the front of the validation and not after it**, which is what the first
clause's ordering requirement is for. `_freeze_json` is an `AfterValidator`, and
pydantic-core validates the recursive `FrozenJson` alias *before* an
`AfterValidator` runs — a walk that costs Python stack per level, and therefore
one that can refuse first, with its own `recursion_loop` diagnostic, whenever the
recursion limit is low enough to bring its threshold under the ceiling. A check
placed after it would then hold only for a range of `sys.getrecursionlimit()`,
which is the property §3 refuses. The mechanism that satisfies the ordering is a
`BeforeValidator` position on the same annotated alias: it sees the raw input,
which is exactly what `_json_depth` already takes (`object`), and it runs ahead
of everything else. Measured 2026-08-26 with that placement: at
`sys.setrecursionlimit(120)` — below the ceiling — a value of 129, 300 or 5000
containers is still refused with the single `ValueError` naming depth and the
ceiling, where the unguarded alias gives 1276 errors headed "Input should be a
valid string".

A plain `ValueError` and not a named error, for the same reason: the two refusals
already at this site are plain `ValueError`s, pydantic turns them into a
`ValidationError` on the field, and every holder already handles that. A named
error would give callers a second shape to catch for a refusal they already catch.

### 2. Depth is measured before the walk, never inferred from a `RecursionError`

> **Normative.** The depth measurement is an iterative walk that allocates no
> Python stack frame per level, and it completes before `_deep_freeze` is
> entered.

> **Normative.** No implementation of this decision may establish the ceiling by
> catching `RecursionError`, by comparing against `sys.getrecursionlimit()`, or
> by any other means that requires the recursion to have been entered.

This is ADR-0145 §6's own objection, kept: "a check placed *after* the freeze
fires after the recursion it exists to prevent". `_json_depth` in `core/types.py`
is already the iterative walk this needs — breadth-first with an explicit
frontier, stopping once past a limit — and `_json_nodes` beside it is the same
technique for a different question. The measurement this clause requires is a
call to something shaped like `_json_depth`, made before `_deep_freeze` is
entered.

Catching `RecursionError` is refused rather than merely dispreferred. ADR-0145 §6
already described what that guarantee is worth: "unwinding at the recursion limit
leaves the handler almost no stack to run in". A refusal that has to allocate a
message, build a `ValidationError` and unwind through pydantic-core is not a
refusal to construct out of the last few frames of a stack.

### 3. One constant in `core`, fixed at 128 containers

> **Normative.** The ceiling is a single constant in `core`, applied to every
> `FrozenJson` value alike: not configurable, not per-holder, not per-subsystem,
> and never derived from `sys.getrecursionlimit()`.

> **Normative.** That constant's value is **128**, counted in `_json_depth`'s
> vocabulary, in which a scalar is depth 0 and `{}` is depth 1.

**Not configurable, for ADR-0145 §2 clause (b)'s reason.** A configurable ingress
depth would make "is this value acceptable" depend on settings, which is the
property that clause forbids of a rule `core` owns and every consumer calls. It
would also mean two processes reading the same store disagree about whether a
persisted record is loadable.

**Not derived from the recursion limit**, because that is the defect in what
holds today: acceptance must not move when an unrelated dependency raises or
lowers a process-global. A fixed constant is the only form in which the ceiling
is a fact about the type rather than about the process.

**Why 128, stated as arithmetic over the measurements in Context.** It is bounded
from both sides and there is room between the bounds:

- **It must exceed 64**, the `_MAX_SCHEMA_DEPTH` of ADR-0145 §6, and strictly —
  see §4. §6 contemplates "a schema at the bound evaluated against an instance of
  comparable depth", so an instance of 64 containers is a value that decision
  expects to exist, and a ceiling at 64 would refuse it at the ingress before
  evaluation ever saw it.
- **It should leave headroom above that**, because a schema constrains a *prefix*
  of an instance. A schema that stops at 64 containers with
  `additionalProperties` unconstrained says nothing about what nests below, so a
  legitimate instance can be deeper than the deepest schema that binds it.
  Doubling is the smallest simple multiple that grants that headroom without
  reasoning about a distribution nobody has measured.
- **It must sit below the tightest mechanism that walks the value**, with margin.
  The tightest observed is 255 containers, where a model holding one stops
  serialising. 128 is half of it, and less than one seventh of `_deep_freeze`'s
  own 997.
- **It is far above anything real.** Tool schemas and tool arguments in this
  repository nest well under ten containers, which is the same observation
  ADR-0145 §6 made when it chose 64: the bound is headroom, not a ceiling anyone
  meets.

The number is a judgement inside those bounds and this ADR does not pretend
otherwise. What is not a judgement is that it must be *some* fixed number of ours,
strictly between 64 and 255.

### 4. The ceiling sits above ADR-0145 §6's schema bound and does not displace it

> **Normative.** The ceiling of §3 is strictly greater than `_MAX_SCHEMA_DEPTH`,
> so that a `parameters_schema` nested deeper than `_MAX_SCHEMA_DEPTH` and within
> the ceiling is refused by ADR-0145 §6's own check, carrying §6's own reason,
> and by nothing this decision adds.

`parameters_schema` is itself a `FrozenJsonMapping`, so the ingress check of §1
runs on it as a field validator — before the model validator that reads it as a
schema. If the two bounds were equal, the ingress would refuse every schema §6
means to refuse, and §6's message — "parameters_schema cannot be read: it nests
deeper than 64 levels" — would become unreachable, its check dead code, and a
tool author would be told about the wrong bound. Ordering the two, tighter bound
inside looser, is what keeps each refusal saying the thing it knows.

That the tighter bound is on the schema and the looser on the instance is
ADR-0145 §6's own argument, unchanged: evaluation spends more stack per level
than freezing does, so the document that is *evaluated* needs a tighter bound
than the value that is merely *frozen*.

### 5. What the implementation lane pins

> **Normative.** The implementation of this decision lands with tests that pin,
> each verified to fail when the change it covers is reverted: (a) a value at the
> ceiling freezes and a value one container past it is refused with §1's reason;
> (b) **every** field of `core/types.py` whose annotation is `FrozenJsonValue` or
> `FrozenJsonMapping` refuses the same over-deep input the same way, enumerated
> from the models' `model_fields` rather than listed by hand; (c)
> `_MAX_SCHEMA_DEPTH` is strictly less than the ceiling, and a schema between them
> is refused with ADR-0145 §6's reason and not with §1's; (d) with
> `sys.setrecursionlimit` set **below** the ceiling, a value past the ceiling is
> still refused with §1's reason and no `RecursionError` is raised.

Each of these is a claim this ADR makes that would otherwise decay silently, and
two of them are the only mechanical guard on a clause above.

**(b) is enumerated and not listed**, because a hand-written list is a list that
goes stale. Nine fields declare the type as this is written, and the roster the
test builds is what makes a tenth arrive already pinned rather than silently
outside the contract §3 states over "every `FrozenJson` value alike". The
repository has the shape already, in the `model_fields` roster guard #1287 landed
so that a seventh duration field could not go unpinned.

**(c)** is the only guard against a later lane raising `_MAX_SCHEMA_DEPTH` past
the ceiling and quietly killing ADR-0145 §6's refusal, which is a change no reader
of either file would see.

**(d) is what tests §1's ordering and §2's iterativeness at once**, and it is
written with the recursion limit *below* the ceiling for that reason. At the
default limit an implementation that counted depth recursively, or that ran the
check after the recursive alias, would pass every other pin here — the depth
`ValueError` arrives, no `RecursionError` is raised, and nothing distinguishes it
from a conforming implementation. Lower the limit under the ceiling and both
non-conforming placements fail: a recursive counter exhausts the stack, and a
check sitting after the alias never runs because the alias refuses first with its
own diagnostic. This pin is the reason §1 can promise a refusal that does not
depend on `sys.getrecursionlimit()`.

The pins deliberately do **not** assert the upstream numbers in the Context
table. Those are measurements of a dependency at a version, they are what this
decision exists to stop depending on, and pinning them would make an upgrade fail
for having changed something we have just declared we do not rely on.

### 6. What this decision does not settle

- **A value that skipped validation.** `model_construct` builds a model without
  running validators, so a value assembled that way is bounded by nothing here
  and `_thaw_json` would still recurse over it on dump. That is the general
  property of `model_construct` in this codebase rather than anything about
  depth, and no holder uses it.
- **Validating a value *within* the ceiling under a recursion limit set below
  it.** §1's refusal holds at any recursion limit, because the check runs before
  anything that consumes stack. What a limit set beneath the ceiling breaks is the
  other direction: an *acceptable* value nested near the ceiling cannot be
  validated at all, because pydantic-core's recursive alias walk needs stack in
  proportion to depth and will raise `RecursionError` before reaching
  `_freeze_json`. No ceiling of ours can defend against a limit chosen beneath
  itself, nothing in this repository lowers the limit, and the decision is stated
  in terms of what is refused rather than what is accepted for exactly that
  reason.
- **Breadth, size and cost.** A value 10 containers deep and a gigabyte wide
  passes this ceiling. A budget for that is #1108's, unchanged: it needs a unit
  and a constant neither of which is calibratable yet.
- **Migrating a persisted record that the ceiling now refuses.** See Consequences.

### 7. What ratification does to ADR-0145

**ADR-0145 §6 — amended, and the clauses are named.** Two passages of §6's
argument are false about the system, and were false when they were written; the
measurements are in Context. Neither is a marked clause and neither states an
obligation, so nothing ADR-0145 requires changes and no implementation of it is
wrong. What changes is what a reader may take from it:

- §6's instance-half paragraph — "So a payload deep enough to matter exhausts the
  stack on the way in, today, with no schema evaluation anywhere in the picture."
  No construction path reaches `_deep_freeze` with such a payload; the recursive
  alias is validated first and refuses at 257 containers, and the walk survives
  997.
- §6's "What that leaves, stated exactly" paragraph — "there is a window: an
  instance deep enough that the freeze survives and the evaluation does not". The
  window is empty: evaluation cannot descend past the schema, and §6 bounds the
  schema at 64.

**Why that is an amendment and not a stacked addition**, by ADR-0082 §1's test
applied to ADR-0145's text. A reader holding only ADR-0145 reads that an unfixed
stack exhaustion is live in `core` today and that the weakest guarantee in the
document is an unwind at the recursion limit. That reader would prioritise
differently, and would write a handler for a refusal shape that cannot occur. So
they act differently, and the record is owed. It goes on ADR-0145's `Status` line
and in its appended dated note, which is where ADR-0082 §1 puts it and the form
ADR-0136 used against ADR-0015's `Consequences` clause and ADR-0138 against
ADR-0020's.

The alternative reading — that this is a stacked addition, since ADR-0145's
sentences were wrong on their own account rather than made wrong by this decision
— is why the paragraph above names the sentences instead of the section. If those
two sentences stayed as they read, a reader of ADR-0145 would keep a belief this
document has measured to be false, and ADR-0082 §1's test asks about the reader,
not about who is at fault.

**ADR-0145 §14's out-of-scope bullet is not amended.** "A depth bound at the
frozen-JSON ingress … is its own decision. #1107" stays exactly true: it was its
own decision, and this is it.

## Consequences

**Easier.** What a `FrozenJson` value accepts becomes a fact stated in `core`,
asserted by a test in this repository, and identical in every process — instead
of a constant in a dependency's Rust that no file here mentions. A payload
refused for depth says so, in one error, naming the ceiling, at every one of the
nine holders — and, because §1 puts the check ahead of everything that consumes
stack, at every recursion limit rather than only at the default. The two bad
refusals in Context — 1276 errors headed "Input should be a valid string", and a
depth failure reported as "tool has no JSON encoding" — become unreachable
through construction, because both live above 128 and the ceiling refuses first,
as does the one-container band in which a `PlanStep` is accepted and cannot be
dumped, which is a correctness hole rather than a cosmetic one (#1610). And #1107
closes on a full answer rather than on the partial one it asked for: the bound is at the ingress, it reaches every holder,
and the residual it named is shown not to exist.

**Harder.** A shared `core` type's acceptance set narrows, which is the cost
ADR-0145 §6 flagged when it declined to do this. Concretely: a record already
persisted whose depth lies between 129 and 255 containers would stop
revalidating, and ADR-0018 §4 revalidates stored definitions, so it would fail on
the way back in rather than on the way out. No migration is offered. The ceiling
is chosen two orders of magnitude above anything a tool or a planner produces
here, so the exposure is theoretical rather than observed — and a deployment that
finds one is the revisit trigger below, not a case to widen the ceiling for
quietly.

Every construction of a `FrozenJson` value also gains one more pass over it: a
bounded breadth-first walk that stops as soon as the ceiling is exceeded, on the
hottest ingress in `core`, ahead of the two passes (`_deep_freeze` and the
encoder) that already run there. It is bounded where they are not, so it costs
less than either, but it is not free.

`core` also gains a second depth constant next to `_MAX_SCHEMA_DEPTH`, and §5(c)
exists because two constants whose ordering matters are two constants somebody
can invert.

**Revisit if** a tool worth having produces or accepts a payload within a factor
of a few of 128 containers; if a persisted record is found above the ceiling; or
if pydantic-core's recursive-alias walk stops admitting values at the ceiling —
which would not reopen the refusal contract, since §1 runs ahead of it, but would
mean an *acceptable* value could no longer be validated, and the ceiling would
need lowering rather than the argument reworking.

### The strongest case against this decision

Nothing is broken. The crash that was filed cannot happen, the residual that was
filed is empty, and every over-deep payload is already refused — so this ADR adds
a constant, a check on the hottest ingress in `core` and a narrowing of a shared
type's acceptance set, to improve an error message and to stop depending on an
upstream number that has not moved.

The answer is that "an upstream number that has not moved" is the whole of the
current guarantee, and it is not written down anywhere in this repository. The
version floor is open (`pydantic>=2.13.4`), the constant is undocumented, the
guard is a *cycle* detector that catches depth incidentally, and its threshold
moves with a process-global. A property that holds by coincidence, is asserted by
no test, and reports itself in a message that names the wrong cause is not a
property this codebase can be said to have — which is exactly the standard
ADR-0021 §1 applied to encodability when it made the repository run the real
encoder rather than enumerate what could fail.

The narrowing is the real cost and it is accepted knowingly. The mitigation is the
number: far enough above every observed and plausible payload that refusing at it
refuses nothing anyone meant to send, and far enough below every mechanism that
walks the value that the ceiling — not a dependency — is what decides.
