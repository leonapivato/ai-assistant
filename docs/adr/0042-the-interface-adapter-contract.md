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
  collaborator arrives by injection" (`loop.py`) — and ADR-0022 §1 makes that
  binding, not incidental: "`orchestration` may import no concrete subsystem…
  It receives implementations by injection and sees them only through `core`
  Protocols." So the wiring that constructs `SqliteMemoryStore`, a planner, the
  tool registry, the policy and the audit trail and injects them **cannot live in
  `orchestration`**. Nor can it live in an adapter: ADR-0007 has a CLI data-rights
  command "depend only on `core` contracts," reaching a store through the
  `MemoryStore` Protocol "against the contract, not a concrete class" — so the
  layer that *constructs* `SqliteMemoryStore` cannot be an `interfaces/` adapter
  either. Yet that wiring must honour obligations no type can express — the
  `MemoryWriter` must persist to the same store the loop retrieves from
  (ADR-0028 §4), and one object must be injected as both the `ToolRegistry` that
  selects and the `ToolInvoker` that acts (ADR-0029 §8) — so it also must not be
  copied into every front end, where each copy is a place those security-critical
  invariants can go wrong. Where the one composition root lives — barred from
  `orchestration` and from the adapters both — is a decision.

- **How a request enters and a response leaves.** The engine parks on
  `AWAITING_CONFIRMATION` (`Disposition.AWAITING_CONFIRMATION`), and the human
  answer that releases it must come back through the boundary. The rule for who
  *authors* that answer is already set — `ActionPolicy.resolve`'s own docstring
  says leaving the yes/no-to-ruling conversion "to the caller would put the
  authoring of a permission outcome in `orchestration` or, worse, in an interface
  adapter — the business logic golden rule 3 keeps out of `interfaces/`." So the
  boundary must *transport* consent without *authoring* a ruling — and it must
  render a prompt a human can actually judge, which the stage-level
  `StepDisposition` (only `state`, `decision_id`, `tool_id`) does not by itself
  carry. The shape of that round trip needs deciding before an adapter invents one.

- **Whether this needs a new contract.** A new engine-facing Protocol in
  `core/protocols.py`, or a new `core/types.py` boundary type, would be a
  contract change under golden rule 5 — ratified and merged ahead of any
  implementation, its triad a separate lane. Whether one is warranted, or whether
  the existing surface suffices, is the load-bearing decision here.

This ADR decides the contract so the first adapter — a CLI — is built against a
ratified seam rather than inventing one. It decides no code; the façade, the
composition root and the CLI are a later implementation lane.

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
`orchestration` + composition-root-package + `interfaces` lane (§2), **not a
Protocol triad**.

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

- **The façade's result type stays out of `core`.** The façade returns its own
  **`orchestration`-level** result type — a frozen dataclass in `orchestration`,
  like `TurnResult` and `StepDisposition`, each documented as crossing "no
  *subsystem* boundary: only `interfaces`, which already depends on this package,
  ever sees one." It may carry *more* than the raw stage DTOs expose (§4), but it
  is still not a `core` type: promotion to `core` is reserved for "the day a
  subsystem needs to receive one," which this is not.

**Revisit trigger.** If a *second* engine implementation is ever genuinely needed
— a remote engine, a degraded offline engine — the façade is promoted to a
Protocol *then*, contract-first: its ADR and triad land before the second
implementation. Introducing the Protocol now would be blessing a seam with no
second implementation to prove it, the exact failure `CONTRIBUTING.md`'s
spike-first guidance warns against.

### 2. The composition root is a dedicated top-level package, not `orchestration` and not an adapter

The wiring that constructs concrete subsystems and injects them into the engine
lives in a **dedicated composition-root package** — `ai_assistant.app` (name
illustrative; `bootstrap` would do) — exposing a `build_engine(settings)` factory
that returns a façade ready to drive. This is the classic composition root: the
one place, at the application's entry point, where concrete implementations are
named and assembled. It is distinct from every subsystem, from `orchestration`,
and from `interfaces`.

It lives in its own package because **both** natural homes are barred:

- **`orchestration`** — ADR-0022 §1 binds it to import no concrete subsystem, a
  property that ADR calls "the one being tested," not a preference. A
  `build_engine` importing `SqliteMemoryStore` there breaks it.
- **an `interfaces/` adapter** — ADR-0007 has a CLI data-rights command "depend
  only on `core` contracts," reaching a store "against the contract, not a
  concrete class." A layer that *constructs* the concrete subsystems is not an
  adapter obeying that rule.

The composition-root package is the one layer with licence to import both the
concrete subsystems and the engine and wire them together — composition is not
business logic, and every application has exactly one composition root. It is a
single shared package precisely so the wiring obligations that no type can express
are discharged **once**:

- the same `MemoryStore` instance is passed to the loop and to the `MemoryWriter`
  (ADR-0028 §4);
- one object is injected as both the selecting `ToolRegistry` and the acting
  `ToolInvoker` (ADR-0029 §8).

Every adapter (the CLI now, an API later) obtains its engine by calling this
package's `build_engine` and does no construction or injection itself (§6). The
adapter depends on exactly two things — this package's builder and the
`orchestration` façade it returns — and on **no subsystem**, which is what keeps
ADR-0007's rule intact and makes a mechanical guard possible (Consequences). The
façade is the engine the adapter drives, not a concrete *subsystem*, so depending
on it is the "adapter onto the engine" the architecture map intends, not the
concrete-class dependency ADR-0007 forbids.

Because the composition-root package imports concrete subsystems, it joins the
source list of the `lint-imports` contracts that already bind every other layer —
provider SDKs confined to `models/`, and `ai_assistant.testing` confined to tests
— so it gains no licence those forbid; that list edit is part of the
implementation lane, not a `core` contract change.

**The composition root owns the resources it opens, and the façade carries that
ownership out.** The concrete stores are connection-owning —
`SqliteMemoryStore.close()` and `SqliteAuditTrail.close()` each hold an open
SQLite connection — so the builder must (a) close any resource it has already
opened if a later one fails to construct, returning no half-built façade with an
orphaned connection, and (b) hand the successfully-built façade a close/shutdown
path (an async context manager, or an `aclose()`), so a long-lived process — an
API front end above all — has a defined owner that releases every connection on
shutdown rather than leaking it. The shutdown path is **ordered, not abrupt**: it
stops accepting new calls, then **awaits the completion of** in-flight ones before
closing the owned resources, so a store operation cannot run against a connection
closed out from under it. Draining, not cancelling: a store runs its SQLite work in
an `asyncio.to_thread` worker, and cancelling the awaiting task abandons the
coroutine but **not** the worker thread — which would keep using the connection
`close()` then shuts, the very race this exists to prevent — so the façade must let
each in-flight operation *finish* before closing, and stopping request delivery is
not enough on its own. Nothing below the façade enforces this: each store's
`close()` closes its connection directly and takes no lock (its `asyncio.Lock`
guards its own operations, not `close`), so nothing at the store level serialises
`close()` against an in-flight operation, and that ordering has to be the façade's.
Closing the façade when a session ends is the adapter's own lifecycle I/O, which §6
permits.

The builder can only wire a subsystem that *has* a production implementation.
Where one does not yet exist — today the `Planner` has only
`ai_assistant.testing.FakePlanner`, which production code may not import — that
production implementation is a **prerequisite lane** the builder-backed CLI
depends on, named in Consequences rather than assumed here.

### 3. A request enters as one call; a response leaves as one result

The façade's human-facing surface is **request/response**: the adapter hands the
engine one unit of input and receives one result describing what happened. Two
call shapes, mirroring the two the engine already has:

- **A turn.** `converse(utterance: str, *, timeout: timedelta) -> <TurnOutcome>`
  (names illustrative): the adapter passes the user's raw utterance — unrewritten;
  intent is the engine's, not the adapter's — and receives an `orchestration`-level
  result (§1) carrying the answer/plan, whether retrieval degraded
  (`TurnResult.memory_degraded`, which the adapter is obliged to surface, not
  swallow), and the disposition of any step the engine drove — including a parked
  confirmation (§4).

- **A resumption.** When a step parks, the adapter later calls
  `resume(<token>, *, approved: bool, timeout: timedelta) -> <TurnOutcome>` to
  release or refuse it (§4).

Both operations carry the **`timeout` budget** §6 assigns to the adapter: it is
the caller's budget, not the tool's (ADR-0029 §4), which the façade threads to the
executor for the one authorised call a driven step makes. It is keyword-only and
required, mirroring `ToolInvoker.invoke` — the contract has no spelling for
"forever," so the adapter must state a deadline rather than inherit a default.

This `timeout` is the **per-attempt** budget of ADR-0029 §4 — it bounds each
authorised call the engine makes, exactly as `ToolInvoker.invoke` and
`StepExecutor` interpret it — **not** an overall wall-clock deadline for the whole
request. The distinction is dormant today: `respond` ends at the plan and a turn
drives at most one call, so per-attempt and per-request coincide. Once the
plan-driving stage across a plan's steps lands (still "the next slice"), a single
`converse` could run several per-attempt budgets in series, and a 10-second budget
would not bound a two-step turn to 10 seconds. Bounding a whole multi-step request
— an overall deadline the façade decrements and passes on as each step's
*remaining* budget — is a decision that belongs with that plan-driving stage, and
is named here as a follow-on rather than pretended to be solved by threading one
figure through unchanged.

### 4. A confirmation is a prompt the adapter transports, not a decision it makes

When the engine parks a step (`Disposition.AWAITING_CONFIRMATION`), the façade
result it returns must carry two things — and because the adapter is forbidden
from reading the registry, the audit trail, or a `PermissionDecision` (§6), the
*engine* is what assembles them into the result:

- **Confirmation content as structured semantic data** — enough for a person to
  judge the action: the selected tool's human-readable name and description, the
  parameters it would run with (as structured data, not a pre-formatted string),
  **and the recorded `CONFIRM` ruling's own `reason`**. The reason is not optional:
  `PermissionRuling.reason` is defined as "text shown to the user at the moment
  they decide" (`core/types.py`), so a prompt that omitted it would drop the
  policy's own explanation of *why* confirmation is required — an off-device
  disclosure, an unknown cost — which is exactly what the user needs to decide. The
  stage-level `StepDisposition` carries only `tool_id`, and the adapter may not read
  the `PermissionDecision` to recover the rest (§6); so the façade's confirmation
  outcome is a **richer `orchestration`-level DTO** (§1) that the implementation
  lane defines to hold the tool content *and* the ruling reason. This is the
  concrete reason §3's result type is the façade's own, not a raw stage DTO.

  **The engine carries semantic data; escaping is the adapter's, per target.**
  "Safe" is target-specific — a parameter value like `"\x1b[2J"` or Rich markup is
  valid data that a terminal would interpret as a control sequence, but an HTTP or
  TUI front end must encode differently — so the engine cannot pre-escape it
  without corrupting it for some adapter. The DTO therefore carries the values
  as-is (as data), and each adapter neutralises them for its own output on render:
  the terminal adapter strips or escapes control sequences and markup before
  writing; an HTTP adapter encodes for its response. Escaping-for-a-target is
  rendering, which §6 assigns to the adapter.

- **An opaque continuation token** — everything the engine needs to resume the
  exact parked step and no more. Today that is the recorded `CONFIRM`'s
  `decision_id` (carried on `StepDisposition` "until #242 lands") together with
  the step and execution identity `resume` authenticates against
  (`StepRunner._check_parked`). The adapter treats the token as opaque: it stores
  it, relays it back on `resume`, and **never interprets, constructs, or
  re-derives its contents.**

The adapter renders the display content, collects the human's yes/no (I/O), maps
the keypress to `approved: bool` (adaptation), and calls `resume(token,
approved=…)`. It does **not** author the permission outcome.
`ActionPolicy.resolve` — inside `permissions`, reached through the engine — is
what turns `approved` into an `ALLOW` or `DENY` ruling, and only
`approved=False → DENY` is guaranteed; `approved=True` may still be refused by the
policy. The adapter conveys consent; the policy rules on it; the engine records
and executes. An adapter that branched on the token's contents to decide
allow/deny itself would be authoring a permission outcome in `interfaces/`,
precisely what §3's cited rule forbids.

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

The rules in this section govern an interface **adapter** (a CLI command, an API
handler). The composition-root package of §2 is a separate layer, not an adapter,
and it does the wiring an adapter may not.

An adapter (golden rule 3) **may**:

- **I/O and lifecycle**: read argv/stdin/keypresses, write to stdout/stderr,
  manage the TTY, set process exit codes, install logging via
  `configure_logging`, load `Settings`, and close the façade when the session
  ends (releasing the resources §2 gives the façade to own).
- **Adaptation**: parse input into an utterance string; map a yes/no answer to
  `approved: bool`; supply a per-call timeout budget (the *caller's* budget, which
  ADR-0029 §4 explicitly assigns to the caller, not the tool).
- **Formatting/rendering**: render the façade's result, plans, confirmation
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
- construct or inject subsystem implementations — that is the composition-root
  package's job (§2);
- import any subsystem concrete module, or any provider SDK.

The first four forbidden items are business logic. Both imports can now be caught
mechanically: the provider-SDK import already is (`lint-imports`), and because the
composition root is a *separate package* (§2), `interfaces` genuinely needs no
subsystem import — so a new `lint-imports` contract forbidding `interfaces` →
subsystem is well-formed rather than self-contradictory. Adding that contract is a
follow-on issue (it is a `lint-imports` edit, not a `core` change), which is why
this ADR names it rather than shipping it.

### 7. The first concrete interface is the CLI

The first adapter is the **CLI** (`interfaces/cli.py`, the `assistant` console
script). It is responsible for:

- an entry command (e.g. a one-shot `ask` and/or an interactive session) that
  obtains the façade from the composition root, drives one or more turns, and
  renders each outcome;
- prompting for confirmations — rendering the tool content *and* the ruling
  reason (§4) — and relaying the yes/no via `resume`;
- surfacing degraded memory and errors, setting a meaningful exit code, and
  closing the façade on exit (§2).

It is **not** responsible for planning, tool selection, permission decisions,
persistence, subsystem construction, or any engine stage — all of which it
reaches only through the façade, or which the composition root does on its behalf.

Because the plan-driving stage across a plan's steps is itself still being
assembled (`loop.py`: `respond` "still ends at the plan"; step orchestration is
"the next slice"), the CLI's reach grows with the engine's: the *contract* it is
built against is fixed by this ADR now, so the adapter does not have to be
rewritten as those stages land.

## Consequences

**Easier.**

- The first adapter is built against a ratified seam: obtain the façade from the
  composition root, render its result, relay the opaque token. No adapter has to
  invent an entry-point shape or a confirmation round trip.
- No `core` contract change, no triad, no ratify-before-implement gate: the
  follow-up is a single `orchestration` + composition-root-package + `interfaces`
  lane.
- Wiring obligations that no type expresses (ADR-0028 §4, ADR-0029 §8) live in one
  audited composition-root package, not copied into every front end.
- A second front end (HTTP API, TUI) reuses the same façade and composition root;
  only rendering and I/O differ.
- Both boundary rules stay intact and become mechanically checkable:
  `orchestration` keeps ADR-0022 §1's import-purity and the adapters keep ADR-0007's
  ("only contracts, no concrete subsystem"), because the concrete imports are
  quarantined in the dedicated composition-root package — which lets a new
  `interfaces`-may-not-import-subsystems `lint-imports` contract be well-formed.

**Harder.**

- A new top-level package (`ai_assistant.app`/`bootstrap`) is introduced, and it
  must be added to the source lists of the existing `lint-imports` contracts
  (provider SDKs confined to `models/`, testing doubles confined to tests) so it
  inherits their bans; that is an implementation-lane edit, not a `core` change.
- The builder can only wire subsystems that have a production implementation.
  Some do not yet — the `Planner` is `FakePlanner`-only today — so the
  builder-backed CLI depends on those prerequisite lanes landing first; a
  fully-driving CLI is gated on them, and until then the adapter reaches only as
  far as the real subsystems allow.
- Deferring streaming means the CLI renders final states rather than live
  progress; a long turn shows nothing until it resolves. Acceptable for v1,
  revisited when an engine stage emits progress.

**Revisit if** a second engine implementation is genuinely required (promote the
façade to a Protocol, contract-first — §1's trigger); if the continuation token
needs to outlive a process (it must then become a durable, adapter-opaque handle,
which touches the resume path #242 already concerns); or if request/response
proves too coarse for an interactive interface and streaming graduates from a
deferred extension to a decided one.

**Follow-on.** Open issues for: the production subsystem implementations the
builder needs (starting with a production `Planner`); the composition-root
package + façade + CLI implementation lane; the `interfaces`-may-not-import-
subsystems `lint-imports` contract (§6); an overall per-request deadline across a
plan's steps, decided with the plan-driving stage (§3); and the deferred streaming
façade method (§5), to be picked up only when a progress-emitting stage exists.

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

**The composition root lives in `orchestration`.** Give `orchestration` a
`build_engine` factory that imports the concrete subsystems and wires the engine.
*Rejected.* It directly contradicts ADR-0022 §1, which binds `orchestration` to
import no concrete subsystem and calls that "the property being tested."

**The composition root lives inside an `interfaces/` adapter.** Put `build_engine`
in the CLI (or a shared module the CLI imports). *Rejected.* ADR-0007 has an
`interfaces/` command "depend only on `core` contracts," reaching a store "against
the contract, not a concrete class"; a layer that constructs `SqliteMemoryStore`
is not that. A dedicated composition-root package (§2), outside both
`orchestration` and `interfaces`, is the only home that breaks neither rule — and
it also lets the `interfaces`-may-not-import-subsystems guard be added, which an
in-`interfaces` composition root would forbid.

**The composition root is duplicated per adapter.** Let each adapter wire its own
engine inline. *Rejected.* It copies the security-critical wiring obligations
(ADR-0028 §4, ADR-0029 §8) into every front end — the layer golden rule 3 keeps
logic out of — and makes each adapter not thin. A single shared composition-root
package (§2), distinct from the adapters, discharges them once.

**The adapter answers confirmations itself.** Have the adapter map the human's
yes/no straight to an `ALLOW`/`DENY` and hand the engine a resolved decision.
*Rejected outright.* `ActionPolicy.resolve`'s docstring names this as the failure
to avoid — authoring a permission outcome in `interfaces/`. It would also lose the
policy's right to refuse a stale `approved=True` (a confirmation answered long
after it was asked, or one whose request would now be `DENY`). The adapter
transports consent; the policy authors the ruling (§4).

**Reuse `StepDisposition` unchanged as the confirmation result.** Return the raw
stage DTO and let the adapter render from it. *Rejected.* `StepDisposition` carries
only `state`, `decision_id` and `tool_id` — a bare tool id is not enough for a
human to judge "send email to X", and the adapter may not read the registry or
trail to enrich it (§6). The façade's confirmation outcome must carry
engine-assembled, display-safe content (§4); that is why the result type is the
façade's own `orchestration`-level DTO, not a raw stage DTO.

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
