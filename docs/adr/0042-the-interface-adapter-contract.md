# 42. The interface adapter contract

- Status: Proposed
- Date: 2026-07-22

## Context

The request pipeline now runs inside `orchestration`. `LearningLoop.respond`
takes an utterance through intent → context → retrieval → planning; `StepRunner`
takes a single planned step through selection → permission → execution, parking
on a `CONFIRM` and continuing through `resume`; `StepExecutor` performs the one
authorised call. What does *not* yet exist is a way for a human to drive any of
it. `interfaces/` is a ~50-line stub: `cli.py` wires a `typer` app with one
`version` command and a docstring promising it "calls into the (not-yet-built)
orchestration engine." The engine is now built; the adapter is not.

Before the first real adapter is written, four things are undecided, and writing
the adapter first would decide them by accident:

- **The seam.** What does an interface depend on to drive the engine? The
  architecture map calls `interfaces/` "thin adapters onto the engine," and
  golden rule 1 routes cross-*subsystem* traffic through the Protocols in
  `core/protocols.py`. But every Protocol there is a capability the engine
  *consumes* (`MemoryStore`, `Planner`, `ActionPolicy`, …), injected into it.
  Nothing describes the surface the engine *offers* a caller. `lint-imports`
  encodes the asymmetry deliberately: its "subsystems do not import orchestration
  or interfaces" contract names only the seven subsystems as sources —
  `interfaces` is not one of them, and `orchestration` is not a forbidden target
  for it. An adapter importing the concrete engine is permitted by the boundary
  rules as they stand; it is the engine's driver, not a peer subsystem talking to
  another subsystem across a contract.

- **The composition root.** The engine classes import nothing concrete — "Every
  collaborator arrives by injection" (`loop.py`) — which is what lets them run
  against fakes in tests and real subsystems in production. But *something* must
  construct `SqliteMemoryStore`, the real planner, the tool registry, the policy
  and the audit trail and inject them, honouring wiring obligations no type can
  express: the `MemoryWriter` must persist to the same store the loop retrieves
  from (ADR-0028 §4), and one object must be injected as both the `ToolRegistry`
  that selects and the `ToolInvoker` that acts (ADR-0029 §8). That wiring is not
  "thin," and duplicating it in every adapter would copy a security-critical
  invariant into the layer golden rule 3 keeps logic out of.

- **How a request enters and a response leaves.** The engine parks on
  `AWAITING_CONFIRMATION` (`Disposition.AWAITING_CONFIRMATION`), and the human
  answer that releases it must come back through the boundary. The rule for who
  *authors* that answer is already set — `ActionPolicy.resolve`'s own docstring
  says leaving the yes/no-to-ruling conversion "to the caller would put the
  authoring of a permission outcome in `orchestration` or, worse, in an interface
  adapter — the business logic golden rule 3 keeps out of `interfaces/`." So the
  boundary must *transport* consent without *authoring* a ruling, and the shape
  of that round trip needs deciding before an adapter invents one.

- **Whether this needs a new contract.** A new engine-facing Protocol in
  `core/protocols.py`, or a new `core/types.py` boundary type, would be a
  contract change under golden rule 5 — ratified and merged ahead of any
  implementation, its triad a separate lane. Whether one is warranted, or whether
  the existing surface suffices, is the load-bearing decision here.

This ADR decides the contract so the first adapter — a CLI — is built against a
ratified seam rather than inventing one. It decides no code; the façade, the
builder and the CLI are a later implementation lane.

## Decision

### 1. The seam is a concrete `orchestration` façade, not a new Protocol

An interface adapter depends on a single **engine façade** that `orchestration`
exposes as a concrete class, plus the result DTOs that façade returns. It does
**not** depend on any subsystem, and it does **not** depend on the engine's
internal stage objects (`LearningLoop`, `StepRunner`, `StepExecutor`) directly —
those become collaborators the façade composes, addressable to the adapter only
through the façade's own methods.

**We will not add an engine-facing Protocol to `core/protocols.py`, and we will
not add a new `core/types.py` type.** This ADR is therefore **not a contract
change** to the `core` surface: its floor paths (`core/protocols.py`,
`core/types.py`) are untouched, and its follow-up implementation is an ordinary
`orchestration` + `interfaces` lane, **not a Protocol triad**.

The reasoning:

- **The engine is not a peer subsystem.** Golden rule 1 exists so two
  *subsystems* — independently replaceable, each unaware of the others — meet
  only through a contract. The adapter → engine edge is not that shape: there is
  exactly one orchestration engine, the adapter exists solely to drive it, and
  `lint-imports` already permits the import. A Protocol between them would model a
  substitutability that does not exist.

- **A Protocol here would cost a triad for no payoff.** A new Protocol is not a
  free annotation: it obliges a shared conformance suite and a canonical fake in
  `ai_assistant.testing`, landing together (`CONTRIBUTING.md` → "Adding a
  Protocol"). That machinery earns its cost when many implementations must be held
  to one contract. The engine has one implementation and one class of consumer;
  the suite would encode a contract nothing else ever satisfies.

- **The DTOs already belong on this side of the boundary.** `TurnResult` and
  `StepDisposition` are frozen dataclasses in `orchestration`, each documented as
  crossing "no *subsystem* boundary: only `interfaces`, which already depends on
  this package, ever sees one." An adapter consuming them needs no promotion to
  `core`; that promotion is reserved for "the day a subsystem needs to receive
  one," which this is not.

**Revisit trigger.** If a *second* engine implementation is ever genuinely needed
— a remote engine, a degraded offline engine — the façade is promoted to a
Protocol *then*, contract-first: its ADR and triad land before the second
implementation. Introducing the Protocol now would be blessing a seam with no
second implementation to prove it, the exact failure `CONTRIBUTING.md`'s
spike-first guidance warns against.

### 2. The composition root is a builder owned by `orchestration`

The wiring that constructs concrete subsystems and injects them into the engine
lives in a **builder owned by `orchestration`** — a `build_engine(settings)`
factory (name illustrative), kept in its own module so the engine's stage classes
stay injection-pure and import nothing concrete. The builder is the *only* place
the wiring obligations that no type can express are discharged:

- the same `MemoryStore` instance is passed to the loop and to the `MemoryWriter`
  (ADR-0028 §4);
- one object is injected as both the selecting `ToolRegistry` and the acting
  `ToolInvoker` (ADR-0029 §8).

The façade is constructed by this builder and returned ready to drive. An adapter
calls the builder with a `Settings` and receives a façade; it performs **no**
subsystem construction and **no** injection itself. This keeps the security-load
of the wiring in one audited place rather than copied per adapter, and keeps the
adapter thin (§5).

`orchestration` importing concrete subsystems at this builder is consistent with
the boundary rules — `lint-imports` forbids the subsystems from importing
*inward-facing* `orchestration`, not `orchestration` from importing them at its
composition edge — and it is what the wiring layer is *for*. The purity claim
("nothing concrete is imported") is preserved where it matters, the engine
classes, by isolating the concrete imports in the builder module.

### 3. A request enters as one call; a response leaves as one result

The façade's human-facing surface is **request/response**: the adapter hands the
engine one unit of input and receives one result describing what happened. Two
call shapes, mirroring the two the engine already has:

- **A turn.** `converse(utterance: str) -> <TurnOutcome>` (names illustrative):
  the adapter passes the user's raw utterance — unrewritten; intent is the
  engine's, not the adapter's — and receives a result carrying the answer/plan,
  whether retrieval degraded (`TurnResult.memory_degraded`, which the adapter is
  obliged to surface, not swallow), and the disposition of any step the engine
  drove.

- **A resumption.** When a step parks, the adapter later calls
  `resume(<token>, approved: bool) -> <TurnOutcome>` to release or refuse it (§4).

The result the adapter renders is composed from the engine's existing DTOs
(`TurnResult`, `StepDisposition`) — no new boundary type is minted. Rendering
those DTOs to a terminal is the adapter's job and is "thin" (§5).

### 4. A confirmation is a prompt the adapter transports, not a decision it makes

When the engine parks a step (`Disposition.AWAITING_CONFIRMATION`), the result it
returns carries:

- a **human-readable question** — enough for a person to judge the action (the
  selected tool and what it will do), rendered by the adapter; and
- an **opaque continuation token** — everything the engine needs to resume the
  exact parked step and no more. Today that is the recorded `CONFIRM`'s
  `decision_id` (carried on `StepDisposition` "until #242 lands") together with
  the step and execution identity `resume` authenticates against
  (`StepRunner._check_parked`). The adapter treats the token as opaque: it stores
  it, relays it back on `resume`, and **never interprets, constructs, or
  re-derives its contents.**

The adapter collects the human's yes/no (I/O), maps the keypress to
`approved: bool` (adaptation), and calls `resume(token, approved=…)`. It does
**not** author the permission outcome. `ActionPolicy.resolve` — inside
`permissions`, reached through the engine — is what turns `approved` into an
`ALLOW` or `DENY` ruling, and only `approved=False → DENY` is guaranteed;
`approved=True` may still be refused by the policy. The adapter conveys consent;
the policy rules on it; the engine records and executes. An adapter that branched
on the token's contents to decide allow/deny itself would be authoring a
permission outcome in `interfaces/`, precisely what §3's cited rule forbids.

### 5. Streaming and progress are request/response in v1, extensible later

The engine today returns a *final* result per call; it exposes no incremental
progress stream, and no streaming contract exists anywhere in `core`. **v1 is
strictly request/response**: the adapter renders the final outcome of each call,
and multi-step progress is surfaced by rendering the resulting state, not by
live-streaming intermediate events.

If token-level streaming or per-step progress is wanted later, it is added as an
**additive** façade method returning an async iterator of progress events (the
engine's methods are already `async`; the system composes on one event loop), and
it composes with — rather than replaces — the request/response entry. Deferring it
keeps v1 honest about what the engine can actually produce and avoids inventing a
progress-event type before there is an engine stage that emits one.

### 6. What "thin" permits and forbids

An interface adapter (golden rule 3) **may**:

- **I/O**: read argv/stdin/keypresses, write to stdout/stderr, manage the TTY,
  set process exit codes, install logging via `configure_logging`, load
  `Settings`.
- **Adaptation**: parse input into an utterance string; map a yes/no answer to
  `approved: bool`; supply a per-call timeout budget (the *caller's* budget, which
  ADR-0029 §4 explicitly assigns to the caller, not the tool).
- **Formatting/rendering**: render the engine's result DTOs, plans, confirmation
  prompts, degraded-memory notices and `AssistantError`s with Rich; choose
  verbosity and colour.
- **Session shape**: run a read-eval loop over successive turns; hold and relay
  the opaque continuation token between park and resume.

An adapter **may not**:

- author a permission ruling (allow/deny/confirm) — that is `ActionPolicy`;
- plan, infer intent, or select a tool — those are engine stages;
- read or write memory, plan state, or the audit trail directly — only through
  the engine;
- construct or inspect a `ToolCall`, a `PermissionDecision`, or the internals of
  the continuation token;
- construct or inject subsystem implementations — that is the builder's job (§2);
- import any subsystem concrete module, or any provider SDK.

The first four forbidden items are business logic; the last two are also caught
mechanically the moment they touch a provider SDK (`lint-imports`), but the
*subsystem* imports are not blocked by a contract today and are enforced here by
review — a candidate follow-up is to add an `interfaces`-may-not-import-subsystems
`lint-imports` contract, tracked as an issue rather than decided here.

### 7. The first concrete interface is the CLI

The first adapter is the **CLI** (`interfaces/cli.py`, the `assistant` console
script). It is responsible for:

- an entry command (e.g. a one-shot `ask` and/or an interactive session) that
  obtains the façade from the builder, drives one or more turns, and renders each
  outcome;
- prompting for confirmations and relaying the yes/no via `resume`;
- surfacing degraded memory and errors, and setting a meaningful exit code.

It is **not** responsible for planning, tool selection, permission decisions,
persistence, subsystem construction, or any engine stage — all of which it
reaches only through the façade, or which the builder does on its behalf.

Because the plan-driving stage across a plan's steps is itself still being
assembled (`loop.py`: `respond` "still ends at the plan"; step orchestration is
"the next slice"), the CLI's reach grows with the engine's: the *contract* it is
built against is fixed by this ADR now, so the adapter does not have to be
rewritten as those stages land.

## Consequences

**Easier.**

- The first adapter is built against a ratified seam: depend on the façade,
  render its DTOs, relay the opaque token. No adapter has to invent an
  entry-point shape or a confirmation round trip.
- No `core` contract change, no triad, no ratify-before-implement gate: the
  follow-up is a single `orchestration` + `interfaces` lane.
- Wiring obligations that no type expresses (ADR-0028 §4, ADR-0029 §8) live in one
  audited builder, not copied into every front end.
- A second front end (HTTP API, TUI) reuses the same façade and builder; only
  rendering and I/O differ.

**Harder.**

- `orchestration` now has a module that imports concrete subsystems (the
  builder), so its "nothing concrete is imported" property holds for the engine
  *classes* but not for the package as a whole. The mitigation is isolation — the
  concrete imports are confined to the builder module.
- The "adapter must not import a subsystem" rule is review-enforced, not yet
  mechanical; until a `lint-imports` contract is added, a careless adapter could
  reach past the façade without failing the gate.
- Deferring streaming means the CLI renders final states rather than live
  progress; a long turn shows nothing until it resolves. Acceptable for v1,
  revisited when an engine stage emits progress.

**Revisit if** a second engine implementation is genuinely required (promote the
façade to a Protocol, contract-first — §1's trigger); if the continuation token
needs to outlive a process (it must then become a durable, adapter-opaque handle,
which touches the resume path #242 already concerns); or if request/response
proves too coarse for an interactive interface and streaming graduates from a
deferred extension to a decided one.

**Follow-on.** Open issues for: the façade + builder + CLI implementation lane;
the `interfaces`-may-not-import-subsystems `lint-imports` contract (§6); and the
deferred streaming façade method (§5), to be picked up only when a progress-
emitting stage exists.

## Alternatives considered

**A new engine-facing Protocol in `core/protocols.py`.** Model the seam like
every other cross-package edge: an `Engine`/`Assistant` Protocol the adapter
depends on, with a conformance suite and a canonical fake. *Rejected.* It models a
substitutability that does not exist — one engine, one consumer class — and pays
the full triad cost (`CONTRIBUTING.md` → "Adding a Protocol") for it. It also
inverts the meaning of `core/protocols.py`, where every Protocol is a capability
the engine *consumes*; an entry contract is one the engine *provides*, a
different kind of thing. The revisit trigger (§1) keeps this option open for the
day a second implementation actually justifies it, taken up contract-first rather
than speculatively now.

**The composition root lives in `interfaces`.** Let each adapter construct the
subsystems and inject them into the engine itself. *Rejected.* It makes the
adapter not thin, duplicates the security-critical wiring obligations (ADR-0028
§4, ADR-0029 §8) into every front end, and puts the one place those invariants can
go wrong in the layer golden rule 3 exists to keep logic out of. A single builder
(§2) discharges them once.

**The adapter answers confirmations itself.** Have the adapter map the human's
yes/no straight to an `ALLOW`/`DENY` and hand the engine a resolved decision.
*Rejected outright.* `ActionPolicy.resolve`'s docstring names this as the failure
to avoid — authoring a permission outcome in `interfaces/`. It would also lose the
policy's right to refuse a stale `approved=True` (a confirmation answered long
after it was asked, or one whose request would now be `DENY`). The adapter
transports consent; the policy authors the ruling (§4).

**Streaming in v1.** Define the entry point as an async iterator of progress
events from the start, so the CLI can show live progress. *Rejected for now.* No
engine stage emits incremental progress today, so the event type would be
designed against nothing — the "seam ratified with no implementation contact"
`CONTRIBUTING.md` warns against. Request/response matches what the engine
produces; streaming is kept as an additive extension (§5) for when a stage emits
progress.

**Expose the stage objects (`LearningLoop`, `StepRunner`) to the adapter
directly, with no façade.** The adapter holds the loop and the runner and
sequences them itself. *Rejected.* Sequencing the stages — running a turn, then
driving each of the plan's steps, parking and resuming on confirmations — *is* the
orchestration the engine owns; doing it in the adapter would pull pipeline logic
into `interfaces/`. A façade keeps the adapter's surface to "one call in, one
result out" and leaves stage sequencing where it belongs.
