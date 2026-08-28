# 211. The planner is told which capabilities exist, and an act nothing advertises is declined rather than planned

- Status: Proposed
- Date: 2026-08-29
- **Partially supersedes:**
  [ADR-0014](0014-planning-model.md) — §6's `Planner` Protocol block, and only the
  **roster of inputs** `plan` declares. §1 below adds a fourth input, so a reader
  holding only ADR-0014 §6 writes a `plan` that a conforming implementation of this
  decision does not satisfy — golden rule 5's "a Protocol change is a breaking
  change", which is acting differently in ADR-0070 §1's sense and puts this on the
  supersession side rather than the amendment side. It is **partial** in ADR-0070
  §3's sense and deliberately narrow: §6's push-not-fetch rule is not merely kept
  but is the *ground* of the addition, its `async` clause stands, and its
  Protocol-triad practice stands and is what §9 below bills the implementing lane
  for. §2's capability abstraction, §3, §4, §5 and §7 are untouched.
- **Partially supersedes:**
  [ADR-0176](0176-a-planner-may-decline-to-name-a-capability-and-the-decline-is-asserted-rather-than-empty.md)
  — §4's **second** normative clause, the test the prompt states between the two
  envelope shapes, and nothing else of §4 or of that ADR. That clause reads: *"The
  test the prompt states is what the goal requires: a plan envelope where
  accomplishing the goal requires the assistant to act in the world or to reach for
  something this turn has not already been given; a decline envelope where the goal
  is answered from what the turn already carries — the retrieved memories, the
  assembled context, and the conversation rendered into this same prompt. The prompt
  states the test in those terms rather than by enumerating request categories."*
  §4 below replaces it whole: requiring an act is no longer sufficient for a plan,
  and being answered from the supply is no longer the only ground for a decline.
  Everything else of ADR-0176 stands and is relied on — §1's two-shape grammar and
  its marker, unchanged in spelling and in strictness (§5 below); §2's extraction
  predicate; §3's rationale condition, which this decision leans on harder than
  ADR-0176 did; §4's **first**, **third** and **fourth** normative clauses, which
  are about the prompt naming both shapes, the one narrow prompt test, and the
  refusal to pin wording; §§5-10.
- **This is a contract change.** It widens one `Protocol` member in
  `core/protocols.py` — `Planner.plan` — so this ADR is its own PR, ratified and
  merged before anything implements against it (golden rule 5, ADR-0015 §5), and it
  owes **both** lenses, adversarial and architecture (ADR-0015 §1,
  `CONTRIBUTING.md` → "Stop when the required reviews are green"). It adds no
  `Protocol`, no new `core` type, no field on one, no `Settings` field, no member of
  the promoted engine surface, no wire operation and — §8 — no `PROTOCOL_VERSION`
  bump.
- **The implementation's merge binds every open lane.** Widening a `Protocol`'s
  effective member surface is ADR-0209 §4's unconditional limb, so the base move
  that lands §9's implementation costs a review round to every branch open across
  it, whatever that branch touches. The implementing lane is therefore scheduled
  when nothing else is open; this is recorded here so its brief inherits it rather
  than discovering it at `just ship`.
- **Durability clause.** Every quotation below — from an ADR, from
  `core/protocols.py`, from `orchestration/`, from `planning/`, from `app/`, or from
  an issue — is of its text as it stood at this ADR's base, `457caad4`, and not of
  its text on any later day. Where a later ADR changes one of the ADRs cited, this
  ADR is read against the text quoted here and that ADR's own record says what
  moved. This is ADR-0143's clause, taken for its reason.

## Context

### What the owner actually heard

The milestone-20 QA run (#1765) drove a live hub with a real model and filed
**#1772**. Across the run nearly every answer — spoken and typed — spent a clause
of itself apologising for a tool that does not exist. Eight verbatim rows are on
the issue; three are enough here:

| What was asked | What came back |
| --- | --- |
| *Tell me what is on my calendar this week.* | "I wasn't able to pull up your full calendar for this week, because there's no **calendar tool** connected that I can query right now." |
| *Tell me about Alice.* | "I wasn't able to look up Alice for you, because I don't have a tool available to search **contacts**…" |
| *Tell me three things I could do this weekend.* | "…I don't have a tool available to search for **activities**, so I couldn't look anything up." |

Every one of those turns carried `step.disposition = no_capable_tool`. The
assistant answered well *and* apologised for a capability nobody asked about, in
the same breath, on almost every turn.

### Nothing is malfunctioning, which is why this needs a decision

Every stage did what it was ruled to do. ADR-0208 §3 predicted this outcome and
ruled it correct:

> **Normative.** With no memory tool advertised, a plan step naming a
> memory-lookup capability resolves to no advertised name and is reported
> `NO_CAPABLE_TOOL` (ADR-0037 §1). That outcome is correct and is not a capability
> gap to be closed by re-registering a tool.

ADR-0037 §1 is the mechanism it names — `find` returning nothing gives
`NO_CAPABLE_TOOL` and `PENDING → SKIPPED` — and ADR-0170 §5 is what turns that
into prose:

> **Normative.** The stage's instruction to the model requires the answer to state
> what the assistant did **not** do wherever a planned step did not run — skipped
> for want of a capable tool, denied by policy, refused for its arguments, refused
> at the egress binding, ambiguous between tools, or never driven at all — and
> requires it not to narrate as done a step that did not succeed.

So the composing stage is being *honest*, correctly, about a step that should never
have been planned. ADR-0208 §3's second clause says where the defect is:

> **Normative.** A goal answered from the supply the turn already carries is a
> **decline** under ADR-0176 §4's test, not a plan naming a lookup. Where the
> planner names one anyway, the defect is in the plan, and the remedies available
> to a later lane are the ones ADR-0176 and ADR-0170 §5 already provide — the
> prompt's statement of the test, and the composing stage's obligation to state what
> the assistant did not do — not a tool.

### The planner cannot apply a test about capabilities, because it is not told any

`core/protocols.py` declares:

```python
async def plan(
    self,
    goal: Goal,
    *,
    context: CurrentContext,
    memories: Sequence[MemoryRecord] = (),
) -> ActionPlan: ...
```

and `planning/planner.py`'s `_SYSTEM_PROMPT` tells the model to invent a name:

> A step names an abstract CAPABILITY — what must be done — not a specific tool,
> product, or vendor. Use short snake_case names such as `send_email`,
> `search_calendar`, or `book_flight`.

`search_calendar` is in the prompt as an *example*, and #1772's first row is the
model doing exactly as instructed. The planner has no way to know that on this hub
`ToolRegistry.capabilities()` answers `("report_current_time",)` — the one builtin
`app/composition.py` registers unconditionally (ADR-0048), plus `send_email` where
a deployment configured an account (ADR-0148 §6). Given a vocabulary of one, seven
of #1772's eight rows are goals for which the only honest planner output is a
decline.

**This is why #1772's own suggested remedy is not sufficient as stated.** The issue
proposes "a prompt change in `planning/` stating the decline test harder". A prompt
cannot state a vocabulary it has not been given, and ADR-0176 §4's test — *"a plan
envelope where accomplishing the goal requires the assistant to act in the world"* —
is satisfied by "look up the calendar" no matter how hard it is stated. Sharpening
the wording of a test whose terms do not mention the tool set cannot change the
verdict on these eight rows.

### #60 is the open question, and ADR-0016 left it open in terms

ADR-0016 §5 settled the vocabulary's authority and then declined this question by
name:

> **Whether a *planner* is handed the vocabulary is not settled here.**
> `Planner.plan()` takes a goal, context and memories (ADR-0014 §6) and no
> capability list, so telling a planner what exists would need a new input and
> therefore a golden-rule-5 change to a contract this lane does not own. That
> change may well be worth making — a planner that knows the vocabulary proposes
> fewer unsatisfiable steps — but it is a planning-contract decision with its own
> trade-off (a planner constrained to what exists today cannot express a goal the
> system *should* grow to meet), and settling it inside a tools ADR would be
> reaching across the boundary this one spends §5 defending.

and named the delivery: "The registry is the authority on the vocabulary either
way; delivery is issue #60." #60 sketches three options and chooses none — an
optional `capabilities: Sequence[str] = ()` parameter on `plan()`, an
orchestration-owned planning-input type, or leaving it on `NO_CAPABLE_TOOL`
permanently. **#1772 is the measured cost of the third**, on the surface milestone
20's exit test is stated over.

### What is not in dispute, and is used as given

- **The registry is the authority on the vocabulary.** ADR-0016 §5:
  `capabilities()` "reports what is actually advertised, sorted and de-duplicated",
  and the vocabulary is an open string one settled *against* a closed `core` enum.
- **A step names a capability, not a tool** (ADR-0014 §2), and the
  `planning → tool selection` boundary that rests on it stands. Nothing below lets
  a planner name a tool id, see a `ToolDefinition`, or read `risk_level`.
- **The decline envelope exists and is asserted twice over** (ADR-0176 §1), states
  why (§3), and is persisted and composed (§6).
- **The decline's rationale reaches the composing stage.** #1355 is fixed in this
  tree: `orchestration/composing.py`'s `_render_plan` renders the rationale on the
  empty-steps branch, and its docstring says why — *"A decline has no steps, so
  ADR-0176 §3 makes `rationale` the only thing the persisted plan says"*.
- **`planning` imports nothing from `tools`**, by lint-imports and by ADR-0014 §2's
  "neither by import nor in spirit". Nothing below changes that: a *string tuple*
  crosses, assembled by `orchestration`, exactly as `context` and `memories` do.

### An honest statement of what this ADR may not settle

- **It does not decide what the turn's supply contains.** #1732 — a planner that
  can ask for re-retrieval — is a different question about a different input, and
  §10 says how the two relate without deciding it.
- **It does not rank, select, or narrow what a capability may be.** ADR-0037 §1's
  refusal to tie-break stands; ADR-0016 §5's open string vocabulary stands.
- **It guarantees nothing about model output.** ADR-0170 §5's last clause is
  general and this decision does not exempt itself from it: a model told the
  vocabulary may still name something outside it. §7 is why that stays safe rather
  than merely regrettable.

## Decision

We will tell the planner what the system can actually do, and rule that a goal
requiring an act nothing advertises is **declined with a stated ground** rather
than planned as a step that resolves `NO_CAPABLE_TOOL` and is narrated as a missing
tool.

### 1. `Planner.plan` receives the advertised vocabulary, as a required input

> **Normative.** `Planner.plan` in `core/protocols.py` declares a fourth input, a
> keyword-only `capabilities: Sequence[str]`, carrying the capability vocabulary
> advertised by the registry the turn's tool-selection stage will resolve against.
> It is the vocabulary `ToolRegistry.capabilities()` answered — an open string
> vocabulary of which the registry is the authority (ADR-0016 §5) — and it is
> nothing else: not tool ids, not `ToolDefinition` objects, not risk, cost,
> reversibility or reach.

> **Normative.** The parameter is **required and carries no default**. A caller
> omitting it is a type error rather than a call that silently plans blind.

> **Normative.** The planner treats the value as the complete statement of what is
> advertised for this turn. It neither re-derives a vocabulary, nor fetches one, nor
> imports any name from `ai_assistant.tools`, nor holds a `ToolRegistry`. ADR-0014
> §6's rule that context and memories are pushed in rather than fetched governs this
> input for the same reason and without exception.

> **Normative.** The planner does not re-sort, de-duplicate or otherwise
> canonicalise the value, and asserts nothing about its order. ADR-0016 §5 already
> obliges `capabilities()` to answer a sorted, de-duplicated tuple, and a second
> normalisation would be a second authority on the vocabulary.

The signature after this decision:

```python
class Planner(Protocol):
    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
    ) -> ActionPlan: ...
```

**The required-ness is the load-bearing half, and it is a departure from
`memories`.** `memories` defaults to `()` and this input does not, which is a
difference worth arguing rather than smoothing over. The two omissions do not cost
the same thing. A call that forgets `memories` plans impersonally — a degradation
of quality against a system whose product thesis is the accumulated user model, but
the same *kind* of plan. A call that forgets `capabilities` would be handed the
empty vocabulary, and §6 makes the empty vocabulary decisive: every goal requiring
an act would decline. So a defaulted parameter turns one forgotten argument at one
call site into a system that silently refuses to act at all, and — worse — refuses
in a way indistinguishable from a deployment that genuinely advertises nothing.
Making it required moves that failure from a live regression nobody can see to a
`mypy` error nobody can merge. `mypy` runs in `strict` mode on this repository, so
that guarantee is mechanical.

**It is a breaking change and it is stated as one.** Golden rule 5 is explicit —
"A Protocol change is a breaking change" — and every `Planner` implementation and
every fake in the tree must accept the new input before this compiles. That is the
cost of the required form and it is paid once, in §9's lane, on a single-process
system with no external implementors.

### 2. Why a parameter, and not a planning-input type

#60's second option — "an orchestration-owned planning-input type" — is rejected,
on two grounds, the first of which is that it cannot be built as named.

**A type crossing this boundary cannot be owned by `orchestration`.** Golden rule 1
is that subsystems talk to each other only through the Protocols in
`core/protocols.py`, and golden rule 2 that `core` depends on nothing else; CLAUDE.md's
conventions add that "public data that crosses subsystem boundaries is a pydantic
model in `core/types.py`". A `planning` implementation annotating a parameter with a
class defined in `orchestration` would import `orchestration` from `planning`, which
`uv run lint-imports` fails as an architecture violation. So the option is really
"a new `core/types.py` model", which is a **second** contract surface — a golden
rule 5 change to `core/types.py` on top of the one to `core/protocols.py` — bought
for packaging alone.

**And the packaging is worse, not better.** A planning-input type earns its keep
only by absorbing `goal`, `context` and `memories` too; a type carrying the
capability list alone is a tuple in a box. Absorbing them would replace ADR-0014
§6's whole roster rather than extend it — a far wider supersession, a rewrite of
every call site, every fake and the conformance suite, and the loss of the property
that a reader of the signature can see what a planner is given without opening a
second file. It also fixes the shape of planning input at exactly the moment #1732
is open about adding to it: a frozen `core` model is *harder* to extend than a
keyword-only parameter list, because every field addition is another `core` change
with its own ADR, where a fourth keyword is one more line in the same block.

**The parameter is the shape §6 of ADR-0014 already chose, applied once more.** Its
stated reason — *"`context` and `memories` are parameters rather than things the
planner fetches itself: the pipeline already assembles context and retrieves memory
before planning, and a planner that reached for them directly would import two
subsystems it has no business importing"* — is true of the vocabulary word for
word, with `tools` as the subsystem. This decision is that sentence extended to a
third input, which is why §11 records the supersession as narrow: the rule is not
contradicted, it is obeyed.

**Rejected: delivering the vocabulary inside `CurrentContext`.** It would need no
Protocol change, which is its whole appeal. `CurrentContext` is the assembled
*situation* — time, calendar, tasks (ADR-0008) — and the tool set is neither
situational nor `context`'s to know; `context` would have to acquire a
`ToolRegistry` to populate it, moving the import this ADR is keeping out of
`planning` into a subsystem with even less business holding it. Hiding a contract
change inside an existing type's payload to avoid declaring one is the failure
golden rule 5 exists to prevent.

### 3. `orchestration` supplies it, from the registry selection resolves against

> **Normative.** The turn's planning stage in `orchestration` reads the vocabulary
> and passes it to `plan`. `planning` performs no read. The read happens within the
> turn, before the planner call, and the plan is judged against the vocabulary as it
> stood at that read.

> **Normative.** The vocabulary passed to the planner is read from **the same
> `ToolRegistry` object** the turn's tool-selection stage resolves the resulting
> steps against. A second registry, or a second snapshot taken from a different
> source, is a defect of this decision.

**The same-object clause is what makes the decision worth anything.** If the
planner were told one vocabulary and selection resolved against another, a step
could be planned against a capability the selecting registry never advertised — the
`NO_CAPABLE_TOOL` narration of #1772, reintroduced by wiring rather than by
prompting, and invisible to every test that stubs one side. `app/composition.py`
already holds exactly one `InMemoryToolRegistry` and injects it as "both the
selecting `ToolRegistry` and the acting `ToolInvoker`"; this clause extends that
single-object discipline to the planning stage rather than inventing a new one.

**Nothing is withheld from this input, and nothing needs to be.** ADR-0203 §1
subtracts what ADR-0199 §3 withholds from a channel of unbounded audience before
the turn plans, and `LearningLoop.respond`'s narrow hook applies it to the context
and the memories alike. The vocabulary is neither: ADR-0016 §6 rules that the
registry "holds configuration, not personal data" — a `ToolDefinition` is Tier 2
configuration declared by code — so there is no record to place, no provenance to
read and no class to withhold. The vocabulary is therefore the same on a spoken
turn as on a typed one, and §7's last clause is what keeps that from leaking into
what is *said*.

### 4. The test the prompt states, restated over the vocabulary

> **Normative.** The planner's system prompt states the advertised vocabulary for
> this turn, as the list of capability names it may name, and states that the names
> in that list are the only ones a plan step may carry.

> **Normative.** The test the prompt states is what the goal requires, judged
> against that list. A **plan** envelope where accomplishing the goal requires the
> assistant to act in the world, or to reach for something this turn has not
> already given it, **and** a capability in the stated vocabulary can carry each
> such step. A **decline** envelope in either of two cases: the goal is answered
> from what the turn already carries — the retrieved memories, the assembled
> context, and the conversation rendered into this same prompt — or the goal
> requires an act and no capability in the stated vocabulary can perform it. The
> prompt states the test in those terms rather than by enumerating request
> categories.

> **Normative.** Where the ground is the second, the prompt requires the decline's
> `rationale` to say, in the assistant's own words, what the goal would have needed
> and that the assistant cannot do it. It may not name a capability, a tool, a
> product or a vendor that the stated vocabulary does not contain.

This replaces ADR-0176 §4's second clause and keeps everything around it. §4's
first clause — the prompt states both legal shapes and states the decline as "a
legitimate, expected outcome … not as a fallback, an error path or a last resort" —
binds unchanged, and now binds over a wider set of goals. §4's third clause, the one
narrow prompt test naming `no_capability_needed` and rendering the decline envelope,
binds unchanged. §4's fourth clause binds unchanged and is worth restating because
it constrains §9: **no test may string-match the wording** of the test between the
shapes. An assertion that the prompt contains a particular sentence "fails on every
rewording that improves the instruction and passes on every rewording that guts it".

**The third clause is the one that answers #1772 directly.** The eight rows are not
merely a wrong envelope; they are a *fabricated referent* — "no calendar tool
connected", "no tool available to search contacts" — describing a tool that was
never registered, never selected and never called. ADR-0170 §5's obligation is to
say what the assistant did **not** do, and it was discharged faithfully over a plan
that had invented the thing being disclaimed. Requiring the rationale to name the
*act* rather than a tool moves the honesty from "I have no calendar tool" to "I
cannot look at your calendar" — one sentence, once, about something true.

**Naming the two directions concretely, as ADR-0176 §4 does**, since the boundary
is again the behavioural heart. *"What do you know about me?"* declines, on ADR-0176
§4's own ground, unchanged: the beliefs that answer it are already rendered above.
*"Send Ana an email"* plans **where `send_email` is in the stated vocabulary**, and
declines where it is not — which is the clause that moves. *"What is on my calendar
this week?"* declines on the new ground wherever no calendar capability is
advertised, which today is every deployment.

### 5. The decline is the envelope ADR-0176 already ruled, with a stated ground

> **Normative.** A decline on either ground is the decline envelope of ADR-0176 §1,
> unchanged: `steps` a list of length zero, `no_capability_needed` the JSON boolean
> `true`, and a non-blank string `rationale` (ADR-0176 §3). This ADR adds no
> envelope key, no marker, no second shape and no field to `ActionPlan`. ADR-0176
> §1's grammar, its strictness rule and its inertness rule are untouched, as are
> §2's extraction predicate and §5's repair message.

> **Normative.** The `no_capability_needed` marker keeps its spelling and its
> meaning is the structural one ADR-0176 §1 gives it: it asserts that this envelope
> names no capability. It is not read, and may not be cited, as an assertion that
> the goal needed none. Which of §4's two grounds applies is stated by the
> `rationale` and nowhere else.

**A second marker key was the obvious alternative and it buys nothing.** The two
grounds are genuinely different in kind — "nothing needed doing" against "something
did, and I cannot" — so a `no_capability_available` key beside the first is a
natural design. It fails on what ADR-0176 §8 already ruled about where the envelope
lives:

> **Normative.** `no_capability_needed` is a key of the planner's *prompt-level JSON
> envelope*, which is a private protocol between `ModelBackedPlanner` and the model
> it prompts. It is not a field of `ActionPlan`, is not persisted, and crosses no
> subsystem boundary. What crosses the boundary is an `ActionPlan` whose `steps` is
> empty and whose `rationale` says why.

A second key therefore reaches no consumer. Downstream of extraction the two grounds
produce the identical artefact — `steps=()` and a rationale — and the only stage
that could act on the difference, the composing stage, is given the rationale and not
the envelope. So the key would cost ADR-0176 §1's grammar (a third legal shape, or a
fourth), a re-supersession of ADR-0071's predicate, and a doubled strictness and
inertness test matrix, in exchange for a distinction nothing can read. Where a later
decision genuinely needs the ground *structurally* — to branch on it, to count it, to
place it — that decision adds a field to `ActionPlan`, which is a `core` change with
its own ADR, and it will be able to point at a consumer. This one cannot.

**The misnomer is real and is answered rather than denied.** A key spelled
`no_capability_needed` set to `true` on a turn where a capability plainly *was*
needed reads wrong, and a reviewer is right to notice. Three things make it
tolerable: ADR-0176 §1 defines the marker structurally and never defines it as a
claim about necessity; ADR-0176 §8 keeps it out of every durable record, so no audit
row ever carries the word; and renaming it would supersede §1's grammar, §2's
predicate and §5's message to change a token that exists only between one prompt and
one parser. The cost of the misnomer is paid by a reader of `planning/planner.py`,
once; the cost of the rename is paid by three ratified sections and their test
matrices. Where §9's lane names the key in a docstring it says what this clause
says.

### 6. The empty vocabulary is a legal input with a stated behaviour

> **Normative.** An empty `capabilities` is a legal input and never an error. The
> planner raises nothing, refuses nothing and enters no repair round on account of
> it.

> **Normative.** Under an empty vocabulary no plan envelope is available, because
> §4's test admits a step only where a listed capability can carry it and no
> capability is listed. Every goal is therefore answered by a decline: on ADR-0176
> §4's original ground where the turn's supply answers it, and on §4's second ground
> otherwise.

**The correction is worth making explicitly, because the empty case is *not*
today's default.** `app/composition.py` registers `current_time` unconditionally —
advertising the capability `report_current_time` (ADR-0048) — and `send_email` where
a deployment configured a connection and an endpoint (ADR-0148 §6, ADR-0154 §6). So
a default hub's vocabulary is a tuple of one, and #1772's hub was answering with one
capability advertised rather than none. ADR-0208 §1 removed the *memory* tool; it did
not empty the registry. The empty vocabulary is nevertheless a state a deployment can
reach — no builtin, no integration — and it is the state every fake and every
conformance case will exercise, which is why it is ruled here rather than left to an
implementation's judgement.

**An empty vocabulary is not a broken system, and the behaviour above is the
honest one.** A hub advertising nothing can genuinely perform no act; a planner that
kept naming capabilities under one would be producing plans whose every step is
known in advance to skip. What the owner hears in that state is an answer composed
from the supply, and — where they asked for an act — one sentence saying the
assistant cannot do it. That is a smaller and truer thing than the eight rows of
#1772.

### 7. What is preserved: the signal, the skip reason, the alias layer, and the answer

**#60's real objection is that blindness carries signal, and the signal survives.**
Its words: *"a planner constrained to what exists today cannot express a goal the
system **should** grow to meet — and 'the plan named something we cannot do yet' is
useful signal, not only failure."* That is right, and it is why this decision routes
the case to a decline that *states its ground* rather than to a silent refusal.

> **Normative.** A goal the system cannot meet remains recorded. The decline's
> `rationale` is persisted on the `ActionPlan` through the `PlanStore` (ADR-0014
> §5, ADR-0176 §6), reaches the composing stage through `_render_plan`'s
> empty-steps branch, and reaches the owner as one sentence in the answer. No
> stage is left to infer that the goal went unmet.

**The trade is stated rather than hidden: a structured signal becomes a legible
one.** Before this decision the record was `PlanStep.capability = "search_calendar"`
with `skip_reason=NO_CAPABLE_TOOL` — a machine-countable string, and an *invented*
one, naming a capability nobody had declared and no vocabulary contained. After it
the record is a sentence naming the act. The sentence is better evidence of what the
owner wanted and worse input to a counter. Nothing in the tree counts those strings
today, so nothing regresses; a later decision that wants demand measured should add
a structured field rather than mine an invented capability name, and §10 records it
as open.

> **Normative.** `SkipReason.NO_CAPABLE_TOOL` is not removed, narrowed or
> deprecated, and ADR-0037 §1's three-case table is untouched. A plan step whose
> capability resolves to no candidate is still reported `NO_CAPABLE_TOOL`, and
> ADR-0208 §3's first clause still rules that outcome correct.

That clause matters because the path stays reachable. ADR-0170 §5's final
clause — *"No clause of this ADR is a guarantee about the content of model output,
and none is read as one"* — is general, and this ADR claims no exemption: a model
handed a one-name vocabulary may still emit `search_calendar`. What changes is that
doing so is now a *departure from an instruction that names the alternative*, rather
than compliance with a prompt that supplied no vocabulary at all. The skip path is
the floor under that, and removing it would turn a model's mistake into an
unhandled state.

> **Normative.** ADR-0053's selection-time capability alias layer is untouched. Its
> four branches — exact, surface variant, curated synonym, unknown — still resolve an
> emitted name against what the registry advertises, and this ADR neither bypasses
> nor pre-empts it.

The alias layer becomes the safety net rather than the routine path, which is what a
safety net should be. A planner told the vocabulary will mostly emit names from it
exactly; the variant and synonym branches keep catching the case where it does not.

> **Normative.** The composing stage's inputs are unchanged. ADR-0170 §5's list is
> what the stage is given, and the capability vocabulary is not added to it. No
> answer gains the ability to enumerate what tools this hub has, or to state that a
> particular integration is or is not connected, beyond what the step account and
> the plan's own rationale already carry.

**That clause is a disclosure boundary, not book-keeping.** Handing the composing
stage the vocabulary would be handing a model an inventory of the owner's connected
accounts and inviting it to read one out on a channel whose audience ADR-0199 §3
governs. The planner needs the list to decide; the answer does not need it to be
honest. A rationale saying "I cannot look at your calendar" is true and names
nothing; a reply enumerating "I have `report_current_time` and `send_email`" would be
a capability listing this ADR does not authorise. Where a later decision wants the
owner told what the assistant can do, that is a product surface with its own
placement question and its own ADR.

### 8. Scope, and no `PROTOCOL_VERSION` bump

> **Normative.** This ADR widens exactly one member of one `Protocol` in
> `core/protocols.py`. It adds no `Protocol`, no other member, no `core/types.py`
> type and no field on one, no `Settings` field, no member of the promoted engine
> surface, no wire operation, no tool and no registry entry. `ToolRegistry`,
> `MemoryStore`, `ContextProvider`, `PlanStore` and `AssistantEngine` are unchanged
> in signature and in meaning.

> **Normative.** `PROTOCOL_VERSION` does not move for this change.

**The version rule is applied rather than asserted past.** ADR-0124 §9's test is
that `PROTOCOL_VERSION` is bumped by any change after which a frame a conforming
peer at the new version may send would be refused by a conforming peer at the old
version, or would be accepted by it with a different meaning. `Planner` is not on
the wire: `wire/surface.METHODS` is derived from `AssistantEngine`, whose methods
this ADR does not touch, and no client constructs a plan, names a capability or
sees this parameter. No frame changes in either direction, so neither limb bites.

> **Normative.** Nothing here authorises egress, registers or designates anything,
> relaxes a permission floor, or is cited toward a destination or a grant. ADR-0017
> §1 and §3, ADR-0021 §5, ADR-0148 §3, ADR-0154 §2 and ADR-0192 are untouched. The
> vocabulary is Tier 2 configuration (ADR-0016 §6, ADR-0004 §1) and no clause below
> turns it into a record, a memory or a disclosure.

### 9. What the implementing lane owes, and what it may not touch

> **Normative.** The implementation lands as its own PR after this ADR merges
> (golden rule 5, ADR-0015 §5), and it lands as one unit: the widened Protocol, the
> conformance clause, the canonical fake, the model-backed planner, the loop's read
> and the composition wiring. Shipping the Protocol without the conformance suite
> and the fake is the split ADR-0014 §6's triad practice forbids.

The lane's work, stated so its brief does not have to rediscover it:

1. **`core/protocols.py`** — `Planner.plan` gains the parameter of §1, with a
   docstring stating that it is the advertised vocabulary, that the planner does
   not fetch one, and that an empty value is legal and means §6's behaviour.
2. **The shared conformance suite** — `PlannerContract` gains a case that a
   conforming implementation accepts the input, one that it accepts an empty
   vocabulary without raising, and one that it does not require the value to be a
   `tuple` specifically. It may not assert *which* envelope a given implementation
   returns for a given goal: the fake's plan is scripted and a model's is not.
3. **The canonical fake** — `FakePlanner` in `ai_assistant.testing` accepts the
   input and records the vocabulary it was given, so a test over the loop can assert
   what the planner was told without a model.
4. **`planning/planner.py`** — `ModelBackedPlanner.plan` threads the value into
   `_SYSTEM_PROMPT`'s rendering, which states the vocabulary, states §4's test over
   it, and states §4's third clause about the rationale. `_repair_prompt` is
   unchanged in what it steers toward (ADR-0176 §5) and states no vocabulary of its
   own beyond what the system prompt carries.
5. **`orchestration/loop.py`** — the planning stage reads `capabilities()` from the
   injected registry, within the turn and before the planner call, and passes it.
   `LearningLoop` gains the registry as an injected contract.
6. **`app/composition.py`** — the loop is handed **the same** `InMemoryToolRegistry`
   object already injected as the selecting registry and the acting invoker (§3).
7. **`orchestration/composing.py`** — `_render_plan`'s empty-steps branch currently
   renders the fixed sentence *"Nothing: the planner produced no steps for this
   turn, so no action was taken and none was needed."* Its last four words are false
   on a §4 second-ground decline, and telling the composing model that none was
   needed while the rationale says otherwise is precisely the contradiction ADR-0170
   §5 exists to stop. The lane corrects that sentence so the branch states that no
   step was planned and defers to the rationale for why, without asserting either
   ground.

> **Normative.** The tests the lane owes are: that the vocabulary the loop passes is
> the one the registry answered and comes from the same object selection uses; that
> the system prompt renders a supplied vocabulary and renders the empty case without
> raising; that an empty vocabulary produces no exception at any stage; and that
> `_render_plan`'s empty branch no longer asserts that no capability was needed. No
> test may string-match the prompt's wording of §4's test (ADR-0176 §4's fourth
> clause), and no test may pin a model's choice of envelope for a goal.

> **Normative.** The lane may not add a capability enum to `core`, may not put a
> `ToolRegistry` into `planning`, may not give the composing stage the vocabulary
> (§7), may not add a field to `ActionPlan`, and may not change ADR-0037 §1's
> dispositions. Finding any of those necessary is a stop, not a widening.

**A note on sequencing, because two lanes meet in one file.** Batch #1780's lane C
is editing `orchestration/composing.py` for the spoken register (#1779). Item 7 is
one sentence in a different function of that file and lands later, after this ADR
merges; the implementing lane rebases onto whatever has landed rather than
anticipating it.

### 10. What this decision does not decide

**#1732 — planner-requested re-retrieval — is not decided here, and nothing above
forecloses it.** The two questions are adjacent and separable: this ADR decides what
the planner may *name*, and #1732 asks whether a planner can ask for the turn's
*supply* to be extended before it decides. They meet at one point worth stating —
several of #1772's rows ("preferences", "contacts") are memory lookups a richer
supply could have answered, and under this decision they become declines rather than
invented tools. That is the honest outcome given the supply the turn ran over, and
it is not an argument that the supply was right. Nothing in §4 or §5 constrains the
envelope shape a re-retrieval decision might add: this ADR adds no envelope key and
takes none, ADR-0176 §1's grammar is left exactly as it was, and a third shape or a
new key remains available to a decision that has a consumer for it. ADR-0208 §4
already names the same gap — the possibility "that the second read finds a belief the
first missed" — and points at #1732 for it.

**How often either envelope is chosen is not claimed.** #1772 is eight observed rows
on two scratch hubs, not a measured rate, and this ADR predicts an improvement it
does not quantify. Whether the decline is judged well is a question for a QA pass
after §9's lane lands, and milestone 20's exit surface is the probe already written
for it. This is ADR-0176 §9's honesty about its own change, taken for the same
reason.

**Whether unmet demand should be recorded structurally is left open**, and §7 says
why the free-text rationale is enough for now: nothing counts capability strings
today. A decision that wants demand measured — for a roadmap, for a suggestion
surface, for a "you asked for this three times" prompt — adds a field or a memory
kind and can point at its consumer.

**Whether the owner should be told what the assistant *can* do is not decided**
(§7's last clause). This ADR keeps the vocabulary away from the answer; a capability
listing is a product surface with a placement question under ADR-0199 §3, and it
belongs to whichever decision wants it.

**Ranking, selection and the several-candidates refusal are untouched.** ADR-0037
§1's `AMBIGUOUS_CAPABILITY` case and its refusal to tie-break stand; issue #241 is
still where a selection rule lives.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's *text*: would a
reader holding only the earlier ADR now act differently, or read one of its clauses
more widely than it now holds? Applied ADR by ADR.

**A partial supersession is owed on ADR-0014, and it is §6's input roster.** A
reader holding only ADR-0014 §6 writes the three-input `plan` its block declares,
and under golden rule 5 an implementation of that Protocol does not satisfy the one
§1 above declares — the reader's artefact stops conforming, which is acting
differently in the strongest available sense. ADR-0070 §1 puts a change to what was
decided on the supersession side however small the edit, so this is a supersession
and not an amendment. It is **partial** in ADR-0070 §3's sense and narrow: §6's
push-not-fetch sentence is true word for word after the change and is the *ground*
of §2 above; its `async` clause and its Protocol-triad practice both stand, the
latter as §9's obligation. §2's capability abstraction, the frozen plan, the audit
record and the `planning → tool selection` boundary are untouched — §1 above adds an
input to the planner and takes nothing from the selection stage.

**A partial supersession is owed on ADR-0176, and it is §4's second normative
clause.** That clause is **marked**, and ADR-0089 §3 makes the marked set the whole
of what a marked ADR obligates — so a marked clause going false is a ruling changing
rather than a stale phrase, which is the reasoning ADR-0113's own header note records
for the same shape. A reader holding only ADR-0176 prompts for a **plan** whenever
the goal requires an act, including the seven #1772 rows where nothing advertised can
perform it; §4 above prompts for a decline. The clause is replaced whole rather than
narrowed, because both of its halves move: the plan half gains a condition and the
decline half gains a ground.

**No record is owed on the rest of ADR-0176, and the reading is worth stating.**
§1's clauses are structural — the two shapes, the marker's strictness, its inertness,
the two test obligations — and every one stays true word for word: this decision adds
no shape and no key, and §5 above is explicit that the grammar does not move. §3's
rationale condition is not merely true but load-bearing here, and §4's second-ground
requirement is stacked on it rather than replacing it: a decline still owes a
non-blank rationale, and now owes a particular content on one of two grounds. §5's
repair message steers toward neither shape and still does. §8's non-contract claim is
a claim about **ADR-0176's own** reach — "This decision changes no `core/protocols.py`
and no `core/types.py` surface" — and stays true of it; a later ADR changing one does
not falsify a sentence about what an earlier one changed, which is the reading
ADR-0204 applied to ADR-0203 §4's first clause. §9's deferrals stay accurate, and §10's
supersession records of ADR-0047 and ADR-0071 are untouched: this ADR changes the
*test* the prompt states, not the envelope those records are about.

**No record is owed on ADR-0016.** §5's `capabilities()` clause is unchanged in every
word, and the registry is still the sole authority on the vocabulary. Its paragraph
beginning "**Whether a *planner* is handed the vocabulary is not settled here**" is a
statement about ADR-0016's own scope and about the corpus at its date; it declines to
decide, names the trade-off, and names #60 as the delivery. This ADR is that delivery
arriving. A reader holding only ADR-0016 builds `tools/` identically and would find
no clause of it made false — the sentence *"`Planner.plan()` takes a goal, context
and memories (ADR-0014 §6) and no capability list"* is a description of the planning
contract that ADR-0016 explicitly held open, and the record of the change belongs on
ADR-0014's line, which is where §11 puts it. This is ADR-0082 §1's "stacked addition"
side of the test, and its warning against demanding a record "on book-keeping grounds
alone" is the reason for saying so rather than adding a pair to be safe.

**No record is owed on ADR-0208.** §3's first clause — a step naming an unadvertised
capability is `NO_CAPABLE_TOOL` and that outcome is correct — stays true and §7 above
keeps the path reachable. Its second clause says the defect is in the plan and names
"the remedies available to a later lane"; this is a later lane taking one of them,
which is the clause operating rather than being narrowed. Its third clause — "This
ADR does not change `ModelBackedPlanner`, its prompt, the decline envelope, or any
test of them" — is a statement about ADR-0208's own reach and stays true of it. §4's
before-and-after and §5's scope clauses are about `tools/` and are untouched.

**No record is owed on ADR-0170.** §5's clauses stay true word for word. The stage is
still told what was and was not driven; on a decline there is nothing driven and
nothing to disclaim, and §9's item 7 corrects a *sentence in the assembler* that
§5 never ruled on. §5's no-guarantee clause is not narrowed — §7 above restates it
for this seam. A reader holding only ADR-0170 builds the composing stage identically.

**No record is owed on ADR-0037, ADR-0053, ADR-0047 or ADR-0071.** §7 above states
the first two as untouched and they are: the disposition table and the alias layer
each keep every clause. ADR-0047 and ADR-0071 are about the envelope's shape and its
extraction, and this ADR changes neither.

The two records that *are* owed ride this change, as ADR-0070 §1's second permitted
header edit allows and ADR-0082 §1 requires: each earlier ADR's `Status` line gains
this ADR's `ADR-0211 (<scope>)` pair, accumulating rather than replacing what is
there (ADR-0070 §4), and each gains an appended dated header note. Neither ADR's
Context, Decision or Consequences text is rewritten. ADR-0014's line keeps its
grandfathered `Accepted, partially superseded by` prefix and its existing ADR-0041
pair rather than being restructured to the leading-token form: giving ADR-0041 the
`(<scope>)` its pair lacks would mean this ADR asserting what ADR-0041 replaced,
which is ADR-0041's to state, and ADR-0004's line carries the same accumulating shape
after seven pairs. ADR-0176's line takes the leading-token form of ADR-0070 §4, since
it is `Accepted` today and this is its first pair.

## Consequences

- **The eight rows of #1772 stop being produced.** On a hub advertising
  `report_current_time` alone, a goal needing a calendar, a contact list or a web
  search is declined with one sentence naming the act, instead of planned as a step
  that skips and is then honestly narrated as a tool that never existed.
- **The planner's output becomes checkable against something.** "Did the plan name a
  capability that exists?" is a question with an answer at planning time, where
  before it could only be answered at selection time, one stage too late to change
  the reply.
- **Every `Planner` implementation and fake must change at once**, because the input
  is required (§1). That is a one-PR cost on a single-process system, and it is the
  price of making the omission a `mypy` error.
- **The implementation's merge costs a review round to every open branch**
  (ADR-0209 §4's unconditional limb), so it is scheduled when nothing else is open.
  That is a scheduling cost on the batch, not on this PR.
- **A goal the system should grow to meet is now recorded in prose rather than as an
  invented capability string.** Better evidence, worse arithmetic; §10 leaves the
  structured form to a decision with a consumer.
- **The planner's prompt grows by the vocabulary on every turn.** With a tuple of
  one or two names that is a handful of tokens; a deployment advertising hundreds
  would want a decision about presentation, and none is made here.
- **Two ratified ADRs gain a `Status` pair and a dated note**, and ADR-0176 §4's
  behavioural test now lives in two places — its own third and fourth clauses in
  ADR-0176, its second clause here. That is the cost of partial supersession and
  ADR-0070 §3 rules it acceptable rather than requiring a split.
- **What would trigger revisiting this.** A deployment whose registry is large
  enough that stating it costs real prompt budget; evidence that a
  vocabulary-constrained planner is refusing goals it should have attempted; or
  #1732 landing a supply the planner can extend, which changes what "the turn has
  already given it" means in §4's first ground.

## Alternatives considered

**Leave it on `NO_CAPABLE_TOOL` and sharpen the composing prompt.** #1772's own
suggested remedy, and ADR-0208 §3's second clause names it as one of two available.
It treats the symptom: the plan still invents a capability, the step still skips, and
the composing stage is still asked to be honest about something that never existed —
only more quietly. Every improvement it can make is a wording improvement over a
false premise, and ADR-0170 §5's last clause says wording is the one thing no ADR can
guarantee. Rejected because the defect is upstream of the stage being asked to hide
it.

**An optional parameter defaulting to `()`.** #60's own first sketch, and the shape
most consistent with `memories`. Rejected in §1: with §6's behaviour, the default is
not a neutral absence but a decisive value, and a forgotten argument would produce a
system that refuses to act at all while looking exactly like one that legitimately
advertises nothing.

**A planning-input type.** #60's second sketch. Rejected in §2 on two grounds: it
cannot be owned by `orchestration` without breaking golden rule 1, so it is really a
second `core` surface; and to earn its keep it must absorb ADR-0014 §6's whole roster,
which is a far wider supersession bought for packaging.

**A `Capability` enum in `core`.** Would let the type system check a step's
capability. ADR-0016 §5 already rejected it, in terms — "every new integration would
become a `core` change and therefore a breaking change under golden rule 5, which
contradicts a subsystem whose whole design is self-contained plugins" — and nothing
here reopens it. The vocabulary crosses as strings.

**A second decline marker, `no_capability_available`.** Rejected in §5: it reaches no
consumer, because ADR-0176 §8 keeps the envelope out of every durable record and the
only stage that could branch on the ground is given the rationale rather than the
envelope. It would cost ADR-0176 §1's grammar and ADR-0071's predicate for a
distinction nothing can read.

**Give the composing stage the vocabulary too**, so it can say what the assistant
*can* do. Rejected in §7: it hands a model an inventory of the owner's connected
accounts on a channel whose audience ADR-0199 §3 governs, to make an answer that is
already honest slightly more helpful. A capability listing is a product surface with
its own placement question.

**Deliver the vocabulary inside `CurrentContext`.** Rejected in §2: it avoids
declaring a contract change by hiding one, and it moves the `tools` import into a
subsystem with less business holding it than `planning` has.
