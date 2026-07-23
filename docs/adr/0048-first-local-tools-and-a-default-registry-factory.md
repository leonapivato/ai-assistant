# 48. The first local tools, and a default-registry factory to wire them

- Status: Accepted
- Date: 2026-07-23

## Context

The request pipeline is fully wired end to end — `intent → context → memory →
planning → tool selection → permission → execute → learn` — and every seam it
needs exists: `ToolDefinition`/`ToolRegistry` (ADR-0016, ADR-0018), the
`ToolInvoker` invocation contract (ADR-0029), the permission stage (ADR-0021),
the `StepRunner`/`StepExecutor` join (ADR-0037), and the composition-root engine
(ADR-0042) driven by a real `ModelBackedPlanner` (ADR-0047).

One thing is missing: **there is no tool to run.** `build_engine`
(`app/composition.py`) constructs an *empty* `InMemoryToolRegistry`, so
`ToolRegistry.find(capability)` always returns `[]`, every planned step is
`SKIPPED`/`NO_CAPABLE_TOOL` (ADR-0037 §1), and `assistant ask "…"` can plan but
never *act*. ADR-0016's Consequences called this out — "Nothing can be called
yet … a registry of definitions no executor can invoke" — and ADR-0042's
Consequences named it transitional: "the adapter reaches only as far as the real
subsystems allow … registering tools is a later lane." This is that lane.

This decision is **non-contract.** It implements the *existing*
`ToolRegistry`/`ToolInvoker`/`ToolDefinition`/`ToolImplementation` surface and
adds no `core/protocols.py` or `core/types.py` member. So it is Accepted on
merge rather than ratified contract-first (ADR-0015), and reviewed
adversarial-only.

Three constraints are fixed by prior ADRs and **not reopened here**:

- **A `PlanStep` names an abstract capability, not a tool** (ADR-0014 §2). The
  registry is the authority on the capability vocabulary (ADR-0016 §5); a tool
  advertises a flat string and the selection stage matches on it.
- **`tools/` still transmits nothing off-device.** ADR-0017 §2 leaves the egress
  seam approved and *undesignated* until every §3 condition holds in code and a
  later ADR ratifies it; ADR-0029 §7 inherits that list undischarged. So the
  first tools must be **local-only, with no network or external-service reach**
  — which also sidesteps the open egress-contract questions (#66/#83/#93) rather
  than pre-empting them.
- **Registration is internal to `tools/`** (ADR-0016 §5, ADR-0029 §1): it binds
  a `(definition, callable)` pair and is on neither cross-subsystem Protocol, in
  the way `context/` keeps its `ContextSource` seam behind `ContextProvider`
  (ADR-0008).

## Decision

We will ship a **small set of local, no-egress tools** and a
**default-registry factory** that binds them, and wire that factory into the
composition root in place of the empty registry.

### 1. The first tool set: two read-only, local tools

The set is deliberately minimal, and each choice below is a constraint, not a
preference. **One tool per capability**, so selection among multiple candidates —
the open #241 question — cannot arise (ADR-0037 §1 leaves several candidates a
`PENDING` no-op). **Both tools are read-only** — non-`side_effecting`,
non-disclosing, `NATURAL` idempotency, `FREE` cost — which keeps every open
question this slice is not equipped to answer out of scope at once: no egress
(nothing leaves the device), no idempotency-window measurement (ADR-0029 §5 is
unexercised by a `NATURAL` tool), no spend policy, and no `CONFIRM`-on-write
round-trip needed to prove the path.

**`current_time`** — capability `report_current_time`. A pure-compute tool that
reports the current UTC instant. It takes **no injected subsystem** — only an
optional clock, defaulting to `datetime.now(UTC)` — so it proves the whole
selection→permission→execute→invoke path with zero wiring surface of its own,
and it is the tool that **genuinely closes the loop end-to-end**: at `LOW` risk,
`REVERSIBLE`, disclosing nothing, at a `FREE` cost, every floor in ADR-0021 §5 is
clear of it and the default `ThresholdActionPolicy` returns `ALLOW`, so a plan
naming `report_current_time` runs to a `SUCCEEDED` step with no confirmation.

**`recall_memory`** — capability `recall_memory`. Searches the user's long-term
memory for records relevant to a query, via an **injected `MemoryStore`**
(`core.protocols`), wired in the composition root to the *same* store the loop
retrieves from and the writer persists to. It is the more useful of the two and,
more to the point, it demonstrates the injected-dependency pattern: a tool may
depend on another subsystem, but only through that subsystem's Protocol, wired at
the composition root — never by importing a concrete (golden rule 1). It reads
Tier 1 data locally and transmits nothing, so `reads=(PERSONAL,)` with empty
`writes`/`discloses`.

`remember` — a *write* to memory — is deliberately **not** in this set. It is
`side_effecting`, which drags in the idempotency-guarantee question (a memory
write is not `NATURAL`), and it belongs with a considered answer to "what does
retrying a memory write mean", not a first slice. Recorded as follow-up work.

### 2. Each tool's `ToolDefinition`

Every safety field is declared, never defaulted (ADR-0016 §1). The two
declarations:

| field | `current_time` | `recall_memory` |
| --- | --- | --- |
| `id` | `current_time` | `recall_memory` |
| `capability` | `report_current_time` | `recall_memory` |
| `risk_level` | `LOW` | `MEDIUM` |
| `reversibility` | `REVERSIBLE` | `REVERSIBLE` |
| `side_effecting` | `False` | `False` |
| `reads` | `()` | `(PERSONAL,)` |
| `writes` | `()` | `()` |
| `discloses` | `()` | `()` |
| `cost` | `FREE` | `FREE` |
| `idempotency` | `NATURAL` | `NATURAL` |

- **`current_time` is `LOW`.** Reading a clock touches no stored data, changes
  nothing, and reveals nothing sensitive; there is no lower honest declaration.
- **`recall_memory` is `MEDIUM`, and that is the honest one.** ADR-0016 §3 is
  explicit that risk is *not* constrained by `side_effecting`: "a read-only tool
  that pulls an entire mailbox into a prompt is high risk". Pulling the user's
  own memory into a turn is lower-stakes than that but is still a Tier 1 read, so
  `MEDIUM` — under the default policy this makes it `CONFIRM`, which is the
  correct default posture for surfacing personal memory, and a user who wants it
  auto-allowed lowers their own `confirm_at_risk`. Declaring it `LOW` to make the
  loop close without a prompt would be under-declaring a security control to make
  a demo smoother, which is exactly the forgetful-author failure ADR-0016 §1
  exists to refuse.
- **Both `NATURAL`.** A read is idempotent by nature (ADR-0016 §4): repeating it
  is safe with no key, so neither declares `KEYED` and neither carries an
  `idempotency_window`. This keeps ADR-0029 §5's window machinery unexercised,
  which is honest for tools that have no window.
- **`discloses` is empty for both.** Neither sends a byte off the device;
  `recall_memory` returns records *into* the local pipeline, which is a read, not
  a disclosure (ADR-0016 §3 tracks off-device transmission).

Each definition carries a `parameters_schema` (JSON Schema): an empty object for
`current_time`, and `{query: string (required), limit: positive integer}` for
`recall_memory`. The schema is **carried, not yet enforced** — ADR-0016 §7 defers
selection-time validation against it — so each callable validates its own inputs
defensively and raises on a bad argument, which the seam classifies `INTERNAL`
(ADR-0029 §3). No message a callable raises interpolates a parameter value, so
nothing untrusted reaches the Tier 2 failure text or a log.

### 3. `build_default_registry` — a factory that keeps registration internal

```python
def build_default_registry(*, memory: MemoryStore, now: Clock = _utcnow) -> InMemoryToolRegistry:
    """Return the populated one-object registry+invoker the composition root wires."""
```

`tools/` exposes one factory that returns the populated
`InMemoryToolRegistry` — the canonical one object implementing **both**
`ToolRegistry` and `ToolInvoker` over one id→`(definition, callable)` map
(ADR-0029 §1). The composition root calls it and injects the *single* returned
object as both the selecting `registry` and the acting `invoker` (ADR-0029 §8),
so the id that selection reports and the id `invoke` acts on are the same id, by
construction.

The factory is the shape ADR-0016 §5 anticipated: **"orchestration cannot compose
a registry from parts; it receives one already populated, which is what injection
means here anyway."** Which tools exist, and the `(definition, callable)` binding
of each, stays inside `tools/`; the composition root supplies only the injected
dependencies a tool needs (`memory`) and takes back a ready registry. The
factory's dependencies are Protocols (`MemoryStore`), so `tools/` imports no
concrete of another subsystem (golden rule 1).

## Known caveat: model↔tool capability alignment (not solved here)

`ModelBackedPlanner` emits capability strings from an **open vocabulary** and is
kept deliberately blind to the tool set (ADR-0014 §2, ADR-0047). So whether the
model, planning a real utterance, names the exact string a tool advertises
(`report_current_time`, `recall_memory`) is **not guaranteed** — a plausible plan
may name `get_time` or `tell_time` and be `SKIPPED`/`NO_CAPABLE_TOOL`, which is a
legitimate, detectable outcome (ADR-0016 §5 reserved the `SkipReason` for exactly
it), not a bug in this slice.

This ADR does **not** try to close that gap. Closing it is a design question with
real options — publishing the registry's vocabulary to the planner (issue #60's
territory, a planning-contract change ADR-0016 §5 left open), a capability
alias/normalisation layer, or a naming convention both sides share — none of
which belongs in a first-tools slice. What this slice proves is that a plan
**naming a tool's advertised capability drives selection→execute** to a real
result; the alignment of the *model's* names with the *registry's* is
**issue #296**, filed alongside this ADR.

## Consequences

- **The CLI acts.** `assistant ask "what time is it"` can now reach a `SUCCEEDED`
  step where before it could only plan — provided the planner names the tool's
  capability (the caveat above). The end-to-end proof is a plan that names
  `report_current_time` driving the real registry through the real
  `StepRunner`/`StepExecutor` to a `SUCCEEDED` step (the implementation's test),
  since the real model emitting the exact string is not guaranteed.
- **No `core/` change.** Both tools implement the existing contracts; nothing in
  `core/protocols.py` or `core/types.py` moves. This is why the decision is
  Accepted on merge and reviewed adversarial-only.
- **The registry is no longer empty, but it is small on purpose.** Two read-only,
  local tools, one per capability. Every hard question a richer tool raises —
  egress, side-effect idempotency, spend, selection among candidates — is out of
  scope by construction, not by omission.
- **A tool may depend on a subsystem, and the pattern is now demonstrated.**
  `recall_memory` takes an injected `MemoryStore` Protocol, wired at the
  composition root, importing no concrete. The next tool that needs memory,
  calendar or notes follows the same seam.
- **Follow-ups, filed as issues rather than TODOs:** model↔tool capability
  alignment (issue #296); and a `remember` write tool, deferred with the
  side-effecting-idempotency question it carries.
- **Revisit when** the first *egress* tool is proposed — that needs ADR-0017 §3's
  conditions discharged and the seam designated, which this ADR explicitly does
  not do — or when capability alignment forces the planner-vocabulary decision.
