# 8. Situational context: `CurrentContext` and a source seam

- Status: Accepted, §§2, 4–5 amended by ADR-0026
- Date: 2026-07-17
- Amended: 2026-07-21 by ADR-0026 — §4's "a valid CurrentContext can always be
  built" now holds for a *conforming* clock: a reading that is naive,
  indeterminate, or outside the localizable range is a wiring bug and raises
  ContextError rather than being attributed UTC. §2's internal source seam gains
  an optional `required` marker — carried by a source, read by the assembler,
  absent meaning optional — so that failure is not degraded; optional sources
  degrade exactly as §4 says. §5's now: Callable[[], datetime] becomes the Clock
  contract of ADR-0026 §1. The startup-time treatment of a malformed timezone,
  the ContextSource/CurrentContext shapes, and everything else in §§2, 4–5
  stand.

## Context

The request pipeline (`CLAUDE.md`) runs `intent → context assembly → memory
retrieval → planning → …`. The `context` subsystem owns the second step:
assembling the situational "right now" that, per [VISION](../../VISION.md) §4,
governs *how much* to present, *when* to interrupt, *which* tools fit, and
**whether to act at all**. It is the first subsystem that will feed the
first end-to-end loop (retrieve context → respond → learn).

VISION §4 lists ten context facets — time, location, device, calendar,
deadlines, active tasks, recent interactions, attention, urgency, goals. Exactly
one has a real source today: the **clock**. Calendar, tasks, goals, and
device/location sensing are all unbuilt subsystems. So the decision here is not
"model all ten"; it is: what is the smallest honest `core` contract that (a)
delivers useful temporal context now and (b) lets each future facet slot in
without reshaping the pipeline?

Unlike memory or commitments, context is **advisory, not critical state**
(VISION §7): it enriches a request but does not need to be durable or perfectly
complete. That shapes the failure and freshness decisions below.

This adds new `core` types and Protocols, so it is ADR-worthy (golden rule 5).

## Decision

We will add a small temporal `CurrentContext` plus a `ContextSource` seam so
context is assembled from independent, composable sources.

### 1. `CurrentContext` — a temporal core, extended later

`core/types.py` gains:

```python
class TimeOfDay(StrEnum):
    MORNING; AFTERNOON; EVENING; NIGHT

class CurrentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    now: datetime                 # tz-aware reference instant
    time_of_day: TimeOfDay
    is_weekend: bool
    within_working_hours: bool
```

Only fields a real source can populate today are modelled. The temporal core is
**required** — it comes from a clock and is always present. Future facets
(calendar, tasks, goals, device, location, attention, urgency) are added in
follow-on ADRs as **optional** fields (e.g. `calendar: CalendarContext | None =
None`), so a producer that predates a facet stays valid: an absent facet is
`None`, which also matches "context is advisory and need not be complete" (§4).
`extra="forbid"` means an internal source contributing an unknown field fails
loudly rather than silently dropping data.

### 2. One `core` Protocol; the source seam stays inside `context/`

`core/protocols.py` gains a single, fully-typed contract:

```python
class ContextProvider(Protocol):
    async def assemble(self) -> CurrentContext: ...
```

The `ContextSource` seam — the composable-sources mechanism — lives **inside the
`context/` package, not in `core`**:

```python
# context/ (internal, not a cross-subsystem contract)
class ContextSource(Protocol):
    @property
    def name(self) -> str: ...
    async def contribute(self) -> Mapping[str, object]: ...
```

This keeps the extensibility seam (per the design decision to build it now)
while ensuring the only data that crosses a subsystem boundary is the typed
`CurrentContext` — honouring the rule that cross-boundary data is a `core`
pydantic model (`CONTRIBUTING.md`). A source's partial `Mapping[str, object]`
contribution is an implementation detail of `context/`, validated at
`CurrentContext(**merged)`; nothing untyped escapes the package. Typed facet
models would be ceremony for a single temporal facet, and are revisited if
several sources make the internal merge unwieldy. `assemble`/`contribute` are
`async` because future sources (a calendar API) are I/O-bound.

### 3. `AssemblingContextProvider` merges sources; collisions are a bug

The concrete provider runs its (internal) sources **concurrently**, merges their
contributions, and constructs `CurrentContext` from the result. Two sources
contributing the **same key** is a wiring bug, not data to reconcile, so it
raises rather than picking a winner. `ClockContextSource` is the one source
today: from an injected clock and configured timezone/working-hours it
contributes the temporal fields.

Adding a facet later is genuinely additive at the `core` contract: add an
**optional** field to `CurrentContext` (ADR) and register an internal source
that contributes it — existing producers and fixtures keep working (the field
defaults to `None`), and the assembler already handles N sources.

### 4. Assembly degrades gracefully; `ContextError` is for wiring bugs

`core/errors.py` gains `ContextError(AssistantError)`. Context is **advisory,
not critical state** (VISION §7), so a source fault must not abort the request
pipeline:

- The **temporal core** is computed from an injected clock and validated
  configuration — it does not perform I/O and does not fail per request (a
  malformed timezone is a startup `ConfigurationError` at `Settings` load, not a
  request-time failure), so a valid `CurrentContext` can always be built.
- A failing **optional** source (future: a calendar API outage) is **skipped**,
  leaving its facet `None`; assembly logs it and returns the rest. Advisory
  enrichment degrades rather than taking down the pipeline.
- `ContextError` is reserved for programmer/wiring bugs the assembler should not
  paper over — chiefly a source-key collision.

### 5. Configuration and clock

`core.config.Settings` gains a `timezone` and a working-hours window
(`working_hours_start`/`working_hours_end`). `ClockContextSource` takes an
injectable `now: Callable[[], datetime]` (defaulting to UTC wall-clock), matching
the memory subsystem, so context is deterministically testable. `assemble()`
computes fresh each call — context is a point-in-time snapshot, not cached state.

### 6. Deferred

- **Every non-temporal facet**, each waiting on its source subsystem, added as an
  optional `CurrentContext` field when it lands.
- **Attention and urgency**, which belong with the proactivity slice (VISION §5)
  and have no signal source yet.
- **Typed facet objects** in place of the internal `Mapping[str, object]`
  contribution — revisited if several sources make the merge unwieldy (§2).

## Consequences

- **The pipeline gets its context step** with useful temporal signal now, and a
  seam that absorbs each future facet as an optional field without reshaping
  `CurrentContext`'s role.
- **New `core` surface is minimal and fully typed:** `CurrentContext`,
  `TimeOfDay`, the `ContextProvider` Protocol, `ContextError`, and two `Settings`
  fields. The `ContextSource` seam is internal to `context/`, so no untyped data
  crosses a subsystem boundary.
- **Context stays advisory and available:** callers read `CurrentContext` to
  shape behaviour; it is never durable state (no store/retention), and a source
  fault degrades the context rather than failing the request.
- **A single temporal source makes the seam feel theatrical until a second
  source exists** — an accepted, deliberate cost of establishing the pattern
  early rather than reshaping later.
- **Adding a facet is a smaller-but-still-real change:** an optional field on
  `CurrentContext` is additive for producers, but it is still an ADR-backed
  `core` type change (golden rule 5), not a silent edit.
- **Revisit when** working hours should become a learned preference rather than
  static config, or when the internal contribution merge gets unwieldy.
