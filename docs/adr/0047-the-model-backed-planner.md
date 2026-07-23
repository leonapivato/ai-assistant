# 47. The model-backed planner: prompt, output envelope, and text→`ActionPlan` extraction

- Status: Accepted
- Date: 2026-07-23

## Context

ADR-0014 landed the planning *contracts* — the `Planner` Protocol, the frozen
`ActionPlan`/`PlanStep` types, the deterministic execution tracker, and the
canonical `FakePlanner` — but deliberately deferred **the model-backed planner
itself** (ADR-0014 §7, "A model-backed planner"): "Decomposing a goal into steps
with an LLM is a follow-on wanting its own ADR (prompt shape, validation of model
output, failure modes)." This is that ADR.

The lane matters now because it unblocks the ADR-0042 composition-root CLI
(issue #290): production code may not import `ai_assistant.testing.FakePlanner`
(`lint-imports` forbids it), so `ai_assistant.app.build_engine` cannot construct
a working engine until a `Planner` it *may* import exists. `FakePlanner` returns
a scripted or empty plan; it is a stand-in for consumer tests, not a planner.

This decision is **non-contract**: it implements the *existing* `Planner`
Protocol and produces the *existing* `ActionPlan` type. No `core/protocols.py` or
`core/types.py` change is made or needed, so it is Accepted on merge rather than
ratified contract-first (ADR-0015), and reviewed adversarial-only.

The constraints are fixed by ADR-0014 and VISION and are **not reopened here**:

- A `PlanStep` names an abstract **capability**, not a tool or registry key
  (ADR-0014 §2). The planner has no dependency on the `tools` subsystem, by
  import or in spirit.
- `ActionPlan` is **frozen** and produced whole.
- **Model output must never set execution status** (VISION §7). The planner
  produces the `ActionPlan` — the "what" — and never touches `ExecutionState`.
- `context` and `memories` are **passed in**, never fetched (a planner that
  reached for them would import subsystems it has no business importing).

What ADR-0014 left genuinely open, and this ADR decides, is: the *prompt* the
planner sends; the *output format* it requests and the *text→`ActionPlan`*
extraction contract (since `ModelProvider.complete` returns a text `Message`, not
typed output); how malformed output is handled; and how the injected seams keep
the planner deterministic under test.

## Decision

We will add a `ModelBackedPlanner` to `src/ai_assistant/planning/planner.py`
implementing the `Planner` Protocol. It turns a `Goal` (plus `context` and
`memories`) into a frozen `ActionPlan` by prompting an injected `ModelProvider`
for a JSON envelope, then extracting and validating that text into `PlanStep`s.

### 1. Injected seams (determinism)

The constructor takes, by injection — mirroring the project's seam pattern
(`CONTRIBUTING.md` → "Determinism"; ADR-0022 §5 for the id factory, ADR-0026 for
the clock):

- `model: ModelProvider` — the one seam to the LLM. No provider SDK is imported;
  golden rule 4 holds.
- `now: Clock` — stamps `ActionPlan.created_at`, guarded by
  `core.clock.checked_clock(owner="ModelBackedPlanner")` exactly as the execution
  tracker and store guard theirs (ADR-0026 §7). A non-conforming reading surfaces
  as `PlanningError`, not the raw `ValueError` `core` raises (ADR-0026 §4).
- `id_factory: Callable[[], str]` — mints the plan id **and every step id**.

`FakeModelProvider`, a fixed clock, and a deterministic counter id factory make a
plan reproducible byte-for-byte, so tests assert exact ids and timestamps.

### 2. The step ids and the plan id are the planner's, never the model's

The model proposes `intent`, `capability`, and `parameters` for each step. It does
**not** supply ids. The planner mints each step's id from `id_factory` and the
plan's id likewise. Two things follow:

- **Unique step ids are guaranteed structurally**, not hoped for from the model —
  the `PlannerContract` obligation holds regardless of what the model returns.
- **The model is kept out of the id space** entirely, which is where execution
  state addresses steps (ADR-0014 §2); a model-chosen id could collide or be
  reused across re-plans.

### 3. The prompt

`plan` sends exactly two `Message`s to `complete`:

- A **system** message stating the planner's job — decompose the goal into an
  ordered sequence of capability steps — and the **exact output envelope**
  (§4), including the instruction that `capability` names an *abstract
  capability* (e.g. `send_email`, `search_calendar`), **not** a specific tool,
  product, or vendor (ADR-0014 §2), and that the reply must be the JSON object
  and nothing else.
- A **user** message rendering the request: the goal's `statement`, `status`,
  `provenance.source`, and `deadline` if set; the `CurrentContext`
  (`time_of_day`, `is_weekend`, `within_working_hours`, `now`); and the retrieved
  `memories`, one line each as `- [{kind}/{source}] {content}`.

Rendering the retrieved memories into the prompt is **what makes the plan
personal rather than generic** (ADR-0014 §6): the accumulated user model reaches
planning as context the model plans against. Each memory's `provenance.source`
is included so the model can weigh a user-asserted fact above an inferred one
(ADR-0005). An empty `memories` is a valid, generic request.

### 4. The output envelope and the text→`ActionPlan` extraction contract

The model is asked to return a **single JSON object**:

```json
{
  "rationale": "<why these steps, one sentence>",
  "steps": [
    {"intent": "<human-readable purpose>",
     "capability": "<abstract_capability>",
     "parameters": {"<name>": "<json value>"}}
  ]
}
```

Extraction from the returned text `Message.content` is deterministic and
precisely this:

1. **Locate the object.** Take the substring from the **first `{`** to the
   **last `}`** (inclusive) and parse it with `json.loads`. This tolerates a model
   that wraps the object in prose or a Markdown code fence without a fragile
   fence parser. If there is no such pair, or `json.loads` fails, extraction
   fails.
2. **Shape.** The parsed value must be a JSON **object** carrying a `steps` key
   whose value is a **non-empty list**. `rationale`, if present, must be a string
   or null; other envelope keys are ignored.
3. **Steps.** Each element of `steps` must be an object with a string `intent`
   and a string `capability`; `parameters` is optional and, if present, must be a
   JSON object (default `{}`). Other step keys are ignored.
4. **Construct and validate.** For each step the planner builds
   `{"id": id_factory(), "intent", "capability", "parameters"}` and validates it
   through `PlanStep.model_validate`, then the whole through
   `ActionPlan.model_validate` with the minted plan id, the goal's id, the
   injected clock's `created_at`, and `rationale`. Pydantic then enforces the
   `core` invariants for free — `capability` non-blank (`Identifier`),
   `parameters` a serialisable `FrozenJsonMapping` deep-frozen at validation,
   step ids unique, the plan frozen. A `ValidationError` at this step is an
   extraction failure.

A **non-empty** `steps` list is required: a production planner returning zero
steps for a goal is indistinguishable from a failure to decompose it, so an
empty plan is treated as "no plan could be produced", not as a valid answer.
(This is the one place the model-backed planner is stricter than `FakePlanner`,
whose empty default plan exists only to record a call.)

### 5. Capability vocabulary: open and unvalidated here

`capability` is an **open, abstract vocabulary** (ADR-0014 §2, §Consequences —
"`capability: str` is an uncontrolled vocabulary"). The planner validates only
that each is a non-blank `Identifier`; it does **not** check a capability against
any tool registry, because that would import the `tools` subsystem and collapse
the `planning → tool selection` boundary. A plan naming a capability nothing
implements is a legitimate, detectable outcome of the *later* selection stage,
not a broken plan.

### 6. Malformed output: bounded repair, then `PlanningError`

Extraction failure (steps 1–4 above) triggers a **bounded repair round**, never
an unbounded loop. On each failed attempt the planner appends the model's bad
reply and a user message quoting the specific failure and re-requesting *only*
the JSON envelope, then calls `complete` again. `max_attempts` bounds the total
number of model calls — one initial request plus up to `max_attempts - 1` repair
rounds — and defaults to **2** (one repair). The constructor rejects a
non-`int` (`bool` included) with `TypeError` and `max_attempts < 1` with
`ValueError`, matching how `orchestration` validates its own bounds. Raising
`max_attempts` is the knob for a provider that proves noisier; whatever its
value, the loop is finite. If the final attempt still fails to yield a valid
plan, `plan` raises **`PlanningError`** naming the last extraction failure — the
Protocol's documented "no plan could be produced".

A **`ModelError` raised by the provider itself** (transport, auth, rate limit,
content filter) **propagates unwrapped**. It is already a typed, actionable
`AssistantError` the caller may want to distinguish, and flattening it into
`PlanningError` would destroy that — the same reasoning ADR-0026 §2 applies to an
exception the injected clock raises on its own account. `PlanningError` is
reserved for the planner's own verdict that the *output* could not be turned into
a plan.

## Consequences

- **The pipeline gets a real planner**, so `ai_assistant.app.build_engine` can
  wire one it may import and the ADR-0042 CLI lane (#290) unblocks.
- **The `planning → tool selection` boundary survives**: the planner emits
  capabilities and imports nothing from `tools`; `lint-imports` stays green.
- **State stays deterministic** (VISION §7): the planner produces only an
  `ActionPlan`; ids, timestamps, and every `StepStatus` remain the property of
  deterministic code.
- **Tests are exact, not shape-based**: `FakeModelProvider` + a fixed clock + a
  counter id factory make a plan reproducible, so unit tests assert the parsed
  capabilities, the minted ids, malformed-output → `PlanningError`, the frozen
  plan, and that memories reach the prompt.
- **The extraction contract is lenient where models are noisy and strict where
  audit demands it**: first-`{`-to-last-`}` slicing absorbs prose and fences, but
  the constructed `PlanStep`/`ActionPlan` must pass every `core` invariant, so a
  malformed decision can never masquerade as a valid audit record.
- **Repair is bounded**: at most `max_attempts - 1` retries (one by default), so
  a stubbornly malformed model cannot spin. Tuning `max_attempts` upward is a
  constructor argument if a provider proves noisier; the loop stays finite at any
  value.
- **Harder / revisit when**: the capability vocabulary is settled by Lane B (does
  the planner gain access to advertised capabilities to prompt against?); a
  provider offering typed/structured output lands (the text-envelope extraction
  could then be replaced by a schema the provider enforces); or plans need
  confidence, alternatives, or step dependencies (ADR-0014 §7). None of those is
  a `core` change this ADR makes.
