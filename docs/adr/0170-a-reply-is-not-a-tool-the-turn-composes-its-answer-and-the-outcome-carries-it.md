# 170. A reply is not a tool: the turn composes its answer, and the outcome carries it

- Status: Proposed
- Date: 2026-08-21
- **This ADR opens `track:conversation` (#1312) and is milestone 17's ruling.** The
  milestone's exit test is the owner asking "what do you know about me?" from an
  enrolled device and receiving a conversational answer drawn from accumulated
  memory. Today that request reaches the end of the pipeline and produces a plan
  listing and one dim line saying no tool is available. This ADR decides why that
  happens and what replaces it.
- **It decides a `core` surface and is therefore reviewed under both lenses.**
  `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a change
  contract-surface "when it is the ADR deciding that surface", even though this PR
  is prose only. §3 is the surface: **one field on `TurnOutcome`**. The
  implementation is a separate lane against this ADR once it is merged (golden
  rule 5, ADR-0015 §5).
- **Amends no ADR and supersedes none, and the case worth arguing is ADR-0085 §4.**
  That section's Group A table lists `TurnOutcome`'s four fields, and after this
  ADR the tree has five — so the question is whether adding a field to a type
  ADR-0085 §4 promoted changes what ADR-0085 decided (ADR-0070 §1: "anything a
  reader would act on differently"). It does not, and the corpus has already
  settled this shape twice on the record. **ADR-0085 §4's Group F row for
  `Disposition` lists five members; the tree has seven.** `INVALID_PARAMETERS` was
  added by ADR-0145 §4 and `EGRESS_UNBINDABLE` by ADR-0152 §9, each on its own
  authority; **neither recorded a supersession against ADR-0085**, and ADR-0145
  does not cite ADR-0085 at all. `Disposition`'s own docstring in `core/types.py`
  names those two ADRs as the record, which is where the record belongs: with the
  ADR that decided the member, not with the one that moved the type into `core`.
  ADR-0085 §4's decision is *which types promote and in what shape at that moment*,
  and a reader implementing ADR-0085 alone still implements it correctly. This ADR
  follows that settled practice rather than opening a third way of doing it.
- **The consequence is disclosed rather than hidden:** ADR-0085 §4's Group A
  `TurnOutcome` row will read short against the tree, exactly as its Group F
  `Disposition` row has since ADR-0145. `core/types.py` carries the pointer, as it
  does for `Disposition`. Nothing in ADR-0085 is edited by this change — it is
  outside this ADR's lane and, on the reading above, owed no record.
- **Nothing here is cited toward the `tools/` egress seam.** ADR-0154 §2's clauses
  stand whole, ADR-0017 §3's fourteen conditions are neither discharged nor
  relaxed, no tool is registered and no destination is approved. §1 argues
  that a reply never reaches that seam at all, which is the opposite of a claim
  about it.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-21**,
  the durability form ADR-0100 established. Refs #1312.

## Context

### The pipeline ends at a tool, and it has no other ending

`ai_assistant.orchestration`'s own module docstring states the ratified pipeline:

> intent understanding → context assembly → memory retrieval → planning →
> tool selection → permission checking → execution → learning/memory updates.

Read the list for what it lacks. Every stage after planning is about *acting*.
There is no stage that speaks. The pipeline as ratified terminates in tool
execution, so a request whose whole point is an answer has nowhere to land.

The code follows the list exactly. `LearningLoop.respond` runs intent, context,
retrieval and planning and returns a `TurnResult`; its module docstring says the
ceiling out loud — "`LearningLoop.respond` **still ends at the plan**".
`Engine._converse` then drives the plan's first step through `StepRunner.run`, and
`StepRunner.run` reaches the dead end in five lines: it resolves the step's
capability, asks `ToolRegistry.find` for candidates, and where there are none it
skips the step with `SkipReason.NO_CAPABLE_TOOL` and returns
`Disposition.NO_CAPABLE_TOOL`. That skip is committed durably to `plans.db`.

`interfaces.cli._render_disposition` renders it:

```python
Disposition.NO_CAPABLE_TOOL: "[dim]No tool is available for this step yet.[/]",
```

And that is the whole of what the user receives. `interfaces.cli._render_turn` —
the renderer for `ask` — prints the plan's rationale, then one numbered line per
step giving its `intent` and `capability`, then that dim line. There is no branch
in it that could print an answer, because there is no field on the value it is
handed that could hold one.

### The planner cannot decline to name a capability

This is the sharpest fact in the tree, and it makes the dead end structural rather
than incidental. `ModelBackedPlanner`'s system prompt closes with:

> `steps` must be a non-empty list.

and `ai_assistant.planning.planner._require_steps` enforces it, raising when
`steps` is missing, not a list, or empty. The planning model is therefore
*obliged* to invent a capability for a request that needs no tool at all. "What do
you know about me?" cannot be planned as "answer this"; it must be planned as some
`snake_case` capability, which nothing advertises, which is skipped, which is
rendered as a missing tool.

One consequence is worth recording because it looks like an escape hatch and is
not: `Engine._converse`'s `if not turn.plan.steps:` branch — the one that prints
"No action was needed." — is unreachable under production wiring, because the
production `Planner` cannot produce an empty plan. It exists for fakes.

### The corpus already writes about an answer that no type carries

The vocabulary has been ahead of the types for some time, and reading the
docstrings back is the clearest evidence that this is a gap rather than a design.

`TurnOutcome.capture_degraded`:

> The answer is still the answer: capture failure degrades a turn rather than
> failing it, because failing would throw away an answer the user already has
> because the record of it could not be written.

`TurnResult.memory_degraded`:

> making :attr:`plan` a *generic* answer rather than a personal one. Reported
> rather than swallowed: an unpersonalised answer is the one failure a user of
> this system most deserves to be told about.

And the CLI, which prints this today above a plan listing:

```python
"[yellow]Note:[/] personal memory was unavailable, so this answer is generic."
```

Three places call something "the answer". In the first it means the tool's side
effect; in the second and third it means the *plan*. Calling a plan an answer is
the conflation this ADR ends. The plan is what the assistant decided to do;
`ActionPlan.rationale` is "Why the planner chose these steps, for transparency".
Neither is a thing said to a user.

### Why "a reply is egress" is a misreading, read against the live rule

Replying was swept into "tools are deferred to MCP", and the sweep looks
defensible until the egress rule is read rather than remembered.

ADR-0017 §1's rule is **partially superseded**. The live rule is ADR-0124 §1:
user data may leave the device from `models/`, from the designated `tools/`
integration seam, **or** from the hub's remote transport between the hub and an
enrolled device — both halves, the listener and the client — and every other
egress is a bug. Three boundaries, not two.

Trace a reply against those three.

- **Composing it** sends the utterance, the assembled context and the retrieved
  memories to a language model. That is `models/`, boundary one, permitted since
  ADR-0004 §2 and unremarkable: it is what `ModelBackedPlanner.plan` already does
  with the *same three inputs* on every turn, and what `ConsolidationStage`
  already does with stored memories.
- **Returning it** puts the answer in the result payload of a request the device
  sent. On a loopback hub that is not egress at all. On the remote listener it is
  boundary three, ratified by ADR-0124 §1, and it carries no data the request path
  did not already carry in the other direction.
- **`tools/` is not on the path.** No registry lookup, no `ToolDefinition`, no
  `ToolInvoker.invoke`, no destination, no recipient, no credential.

So the reply was never on the deferred side of "tools are deferred to MCP",
because it was never a tool. The deferral was about *acting on the world through
third-party integrations*, which is what ADR-0154's seam is for and what
ADR-0017 §3's fourteen conditions guard. Answering one's own user, on the
connection they opened, over a boundary already ratified twice, engages none of
it.

### What ADR-0131 already settled about the shape

ADR-0131 §1 faced the same question for notifications and answered it:

> A disposed notification reaches a device only as the **result payload of a
> request that device sent**. The hub writes no frame on a connection except in
> answer to an outstanding request.

A reply is that shape and an easier case. A notification had to invent a request
to be the answer to — `next_notification`, a long poll — precisely because nobody
asked for it. A reply has its request already: the `ask` is outstanding, the
correlation id is live, and the device is waiting for exactly this. No frame kind,
no push, no multiplexing, and nothing of ADR-0084 §3's serial rule bent.

What the two cases share is worth naming, because it is the same design twice: the
hub speaks to a device only in answer to something the device asked, and the
content it speaks is free text the engine composed for a person to read.
`NotificationCandidate.summary` and `.detail` are that free text on the
notification path. `converse` has no equivalent.

## Decision

### 1. A reply is not a tool, and the pipeline gains a stage that speaks

> **Normative.** Composing a natural-language reply to the user and returning it as
> the result of the request that asked for it is **not** a tool invocation. No lane
> models it as a registered tool, a `ToolDefinition`, a capability resolved
> through `ToolRegistry.find`, or a call routed through `ToolInvoker.invoke`; and
> no reply is gated by ADR-0021 §5's floor, by ADR-0148's per-call machinery, or by
> any clause of ADR-0017 §3, on the ground that it is a reply.

> **Normative.** The request pipeline gains one **terminal composing stage**,
> after execution. Given the turn's goal, its assembled context, the memories
> retrieved for it, its plan, and what became of the step the turn drove, the stage
> composes one natural-language answer, and `AssistantEngine.converse` and
> `AssistantEngine.resume` return that answer as part of the ask's result payload.

> **Normative.** This ADR authorises no byte through `ai_assistant.tools.egress`
> and asserts nothing about it. ADR-0154 §2's clauses stand whole, ADR-0017 §3's
> fourteen conditions are neither discharged nor relaxed, and no lane cites this
> ADR toward designation, toward registering a tool, or toward approving a
> destination.

> **Normative.** The implementing lane amends the pipeline's stage list in
> `ai_assistant.orchestration`'s module docstring to name the composing stage.

A recitable pipeline that omits the stage producing the product is worse than no
list: it is the sentence every later reader will plan against.

### 2. The stage lives in `orchestration`, over contracts it already has

> **Normative.** The composing stage lives in `ai_assistant.orchestration` and
> reaches the model through the injected `ModelProvider` contract. It is not in
> `interfaces/` (golden rule 3 — no business logic in an adapter), not in `models/`
> (golden rule 4 leaves that the provider wrapper), and not in `planning/`, whose
> product is an `ActionPlan`.

> **Normative.** The stage adds **no Protocol and no member to one**.
> `ModelProvider.complete`, `ContextProvider.assemble` and `MemoryStore.search` are
> the whole of what it consumes; each is already ratified, and each is already
> injected into the engine. No triad is owed, because no Protocol is new
> (`CONTRIBUTING.md` → "Adding a Protocol").

> **Normative.** Wiring a `ModelProvider` to the composing stage is a
> composition-root obligation under ADR-0028 §4 and creates no new contract.

`ModelProvider.complete` is already the right shape and says so itself: "Produce
the assistant's next message given the conversation so far", returning "The
assistant's reply as a `Message`". ADR-0066 named the seam's precondition — a
completion request must end awaiting an answer — and a composing stage is the
first caller in the product path for which that description is literal rather than
a metaphor for planning. `ConsolidationStage` is the precedent for an
`orchestration` stage holding an injected `ModelProvider`; it takes one today.

> **Normative.** The composing stage sets no execution status, writes no
> `StepStatus`, transitions no step and produces no `ActionPlan`. VISION §7's rule
> that model output never sets execution status is untouched, and no lane cites
> this ADR toward relaxing it.

That clause exists because VISION §7 is the first objection a careful reader
reaches for, and it is answered rather than waved at: the stage reads the outcome
deterministic code committed and renders prose about it. Nothing flows the other
way.

### 3. The contract surface: one field on `TurnOutcome`, and nothing else

#1312 delegates the question "whether any `core` type change is needed at all —
the response envelope may already carry text, so possibly no contract surface".
**It does not carry text, and one change is needed.**

The whole `converse` return path was read to establish that. `TurnOutcome` has
four fields — `turn`, `step`, `conversation_id`, `capture_degraded` — and
`extra="forbid"`. `TurnResult` has `goal`, `context`, `memories`, `plan`,
`memory_degraded`. `StepOutcome` has `disposition`, `state`, `step_id`, `tool_id`,
`confirmation`. The only free text anywhere in the transitive closure is
`ActionPlan.rationale`, `PlanStep.intent`, `Goal.statement`, `MemoryRecord.content`
and `StepFailure.message`. Not one of them is an answer, and each is documented as
the other thing it is.

> **Normative.** `TurnOutcome` gains exactly one field: `reply`, typed
> `NonBlankEncodableText | None`, defaulting to `None`, carrying the
> natural-language answer the turn composed. It is the only place an answer is
> carried.

`NonBlankEncodableText` rather than `EncodableText`, because §4 gives `None` a
precise meaning and a blank string would be a third state meaning the same thing
less legibly — the reasoning `NotificationCandidate.summary` already applies to
the one line a user is told.

> **Normative.** The field's docstring names this ADR as the decision that added
> it, as `Disposition`'s names ADR-0145 §4 and ADR-0152 §9 for the members they
> added. That pointer is what keeps ADR-0085 §4's Group A table findable from the
> tree once the two diverge (header).

> **Normative.** No other `core` type gains a field, member or discriminator for
> the answer. Specifically: `StepExecution.output` does not carry it,
> `ActionPlan.rationale` does not become it, `PlanStep` gains no `kind`, and no
> member is added to `Disposition`, `SkipReason`, `StepStatus` or `MemoryKind`.

Three refusals in that clause are load-bearing, and each is refused for a reason
rather than for tidiness.

**`StepExecution.output` is refused because the type already forbids it, and
correctly.** It is documented as "The tool's result; only meaningful once
SUCCEEDED", and `StepExecution._claimed_step_is_authorised` requires `bound_tool`,
`approval_ref` and `started_at` on any claimed status. So routing an answer
through it means writing a step that names a tool which does not exist and a
permission decision that was never made. The validator is the type system saying
"a reply is not a tool" before this ADR does; forcing an answer past it would
write a falsehood into durable state, which is what ADR-0014 §4's legal-skip table
and ADR-0037 §1's non-committing dispositions exist to prevent.

**`ActionPlan.rationale` is refused because it is a different claim.** It says why
the planner chose these steps. An answer that displaced it would delete the
transparency the field exists for, and an answer that shared it would make a
client unable to tell an explanation from a reply.

**A `SkipReason` member — "answered instead" — is refused** because it would put
the answer inside the plan's durable record, oblige a row in
`planning.execution._LEGAL_SKIP_REASONS`, and make every step of every plan a
place an answer might live. The answer sits **beside** the plan, which is also why
this ADR does not depend on the planner learning to emit an empty one (#1315).

### 4. When `reply` is absent, stated in both directions

> **Normative.** `reply` is `None` on exactly two shapes and non-`None` on every
> other outcome the two turn calls return:
>
> - a pass whose step reached `Disposition.AWAITING_CONFIRMATION`, where what the
>   user must answer is the `Confirmation` the adapter renders and relays; and
> - a pass whose `turn` is `None` — a resume driven from a **recovered** park
>   (ADR-0052 §3) — where context and memories were never persisted and there is
>   nothing to compose from.

> **Normative.** The implementing lane states that invariant as a
> `model_validator(mode="after")` on `TurnOutcome`, in **both** directions, as
> `StepOutcome._confirmation_matches_disposition` states its own.

Both directions, for that validator's own reason. A `None` on a turn that ran is
an answer the user never got and nobody can point at a contract violation for; a
`reply` beside a parked confirmation is prose competing with a yes/no question the
user must answer, and the prose is what they will read.

Why a park composes nothing rather than composing "I need your permission first":
the confirmation content is already structured semantic data assembled by the
engine for exactly this purpose (ADR-0042 §4), and a second, model-written account
of the same pending action beside it is where the two can disagree. The resume
that follows composes an answer in the ordinary way.

### 5. Non-answerable steps reach the stage, and what is sought of the answer

#1312's second delegated question, and answering it honestly means separating two
things that are easy to run together: what this decision can **guarantee**, and
what it can only **seek**. Nothing in an ADR constrains arbitrary model output. A
conforming `ModelProvider` may return "I sent the email" after a step reached
`Disposition.NO_CAPABLE_TOOL`, and no prompt, clause or test makes that
impossible. So the obligations below are on the **stage's construction** — what it
is given and what it asks for, both of which a lane can discharge and a test can
pin — and the single guaranteed property lives in §6.

> **Normative.** The composing stage is given what became of the plan: which steps
> were driven, which were not driven at all, and for each driven step its
> `Disposition` and its durable `StepStatus` and `failure`. Withholding any of
> those from the stage is a defect of this decision.

> **Normative.** The stage's instruction to the model requires the answer to state
> what the assistant did **not** do wherever a planned step did not run — skipped
> for want of a capable tool, denied by policy, refused for its arguments, refused
> at the egress binding, ambiguous between tools, or never driven at all — and
> requires it not to narrate as done a step that did not succeed. `EXECUTED` is the
> gate's verdict and the named step's `status` and `failure` are the outcome
> (ADR-0084 §8); the instruction carries that distinction to the model rather than
> assuming it.

> **Normative.** Where `TurnResult.memory_degraded` is true, the stage tells the
> model so, and its instruction requires the answer not to claim knowledge of the
> user the turn did not retrieve.

> **Normative.** Until the plan-driving stage (#242) lands, at most a plan's first
> step is driven, and the stage is told which of the plan's steps were not driven —
> not handed the plan alone and left to infer it.

> **Normative.** No clause of this ADR is a guarantee about the content of model
> output, and none is read as one. A composed `reply` may still assert something
> false about execution. Where it does, §6's deterministic account is the record
> and the reply is wrong; a lane that reads this section as licence to relax §6 has
> inverted the decision.

That last clause is the one worth stating plainly, because the alternative — a
marked obligation that no mechanism can discharge — is worse than an honest
limit. "The prompt will handle it" is how an obligation becomes nobody's. What
this decision actually buys is that the stage is never *ignorant* of what
happened, and that the truth is on screen next to the prose whatever the prose
says.

> **Normative.** The stage supplies the step's outcome to the model as rendered
> content inside a message role the model seam admits. It constructs no
> `Role.TOOL` message: `ModelProvider.complete` does not represent a tool exchange
> and refuses a history containing one (ADR-0066), and this ADR does not widen that
> seam.

### 6. The answer is rendered beside the step account, never in place of it

> **Normative.** An adapter renders the composed answer **in addition to** the step
> account it renders today, never instead of it. ADR-0084 §8's rule binds unchanged,
> and no adapter drops the disposition line, the named step's status and failure, or
> the exit code #531 fixed, on the ground that a reply is now present.

> **Normative.** The deterministic step account — the `Disposition`, the named
> step's `StepStatus` and `failure`, and the process exit code derived from them —
> is the assertion this decision guarantees about what the assistant did. The
> composed `reply` is not. Where the two disagree the step account is correct by
> construction, and no adapter, setting or later ADR resolves that disagreement in
> the reply's favour or suppresses the account to remove it.

This is the whole enforceable half, and it is enforceable precisely because it
does not depend on the model. A prompt can ask for honesty; it cannot guarantee
it. But the disposition is a value deterministic code committed and the adapter
prints from, so a model that claims it sent the email is contradicted on the same
screen by a line saying no tool was available — on every turn, without anyone
checking, and whether or not the prompt worked.

It also settles what "the answer replaced the plan listing" would have cost. The
plan listing itself is a rendering choice this ADR does not make; the *step
account* is not a rendering choice, and the two are separable.

### 7. `PROTOCOL_VERSION` moves, and the rest of `wire/` does not

> **Normative.** The lane implementing §3 bumps `PROTOCOL_VERSION` in the **same
> change**, and appends its reason to the running note in `wire/envelope.py` beside
> the existing entries, as every bump since ADR-0131 §4 has.

ADR-0124 §9 decides this and reaches it twice over — "a change to a wire-carried
`core` type that makes a value one peer emits invalid for the other, whether the
change widens or narrows the type", and "any change to the promoted surface's
method set **or to a method's arguments or results**". A single reading of the tree
confirms the first limb bites rather than merely applying: `TurnOutcome` is
`extra="forbid"`, and `wire.surface.return_adapter` validates a result against the
method's declared return annotation, so an older client handed a `TurnOutcome`
carrying `reply` fails with `extra_forbidden` on that member. ADR-0122's optional
`FeedbackEvent.memory_kind` is the precedent ADR-0124 §9 cites for exactly this
shape — a widening that an old peer refuses.

> **Normative.** Beyond `wire/envelope.py`'s version constant and its note, no
> module under `wire/` changes for §3. A result payload takes the shape of the
> method's own declared return annotation (ADR-0085 §10), so the field crosses the
> wire without a second declaration, and no lane transcribes it into a wire-side
> schema.

That is worth stating rather than leaving to relief, because "a new field on the
response type" reads like a protocol change with a matching edit somewhere in
`wire/`, and the codec was built specifically so that it is not.

### 8. Size, failure, and rendering

> **Normative.** The answer is bounded by the existing result-payload ceiling and
> gets **no setting of its own**. `check_payload` already refuses an oversized
> result symmetrically at both ends (ADR-0085 §8), and an answer that would breach
> it is that refusal — never a silent truncation.

> **Normative.** A turn whose composition call fails **raises**; it does not return
> `reply=None`. `None` means the two shapes §4 names and nothing else.

The reason is §4's invariant rather than a preference about errors. Both of §4's
shapes are identifiable from the outcome the client holds — a park by its
disposition, a recovered resume by `turn is None`. A composition failure is not
identifiable from anything in the value, so representing it with the same `None`
would hand a client a value it cannot interpret, which is the falsehood-in-a-
returned-value failure the corpus refuses at `Disposition.INVALID_PARAMETERS`,
at `EGRESS_UNBINDABLE` and at `StepExecution`'s validators. The model seam's
existing failure carries a retryable/routable disposition already (ADR-0066 §3),
which is the right shape for "ask again".

**A successful call can still return an unusable answer, and that gap is closed
here rather than left to the lane.** `Message.content` is `EncodableText`, which
admits the empty string, so a conforming provider may return an assistant message
with no content at all. That call did not *fail*, so the clause above does not
reach it; and §3's `NonBlankEncodableText` cannot hold it, so constructing the
`TurnOutcome` would raise a bare pydantic `ValidationError` out of the engine —
an unclassified failure in place of the model seam's classified one. This is a
reachable path on a conforming provider, not a defensive one.

> **Normative.** The composing stage validates the completion **before**
> constructing a `TurnOutcome`. A completion whose content is blank, or which is
> otherwise unusable as an answer, is raised as `ModelResponseError` — the
> corpus's existing name for "the provider replied, but the response was malformed
> or unusable" — and becomes neither a `reply` nor a `None`. No pydantic
> `ValidationError` from `TurnOutcome` construction reaches a caller of the two
> turn calls.

> **Normative.** A composed answer is engine-supplied text, and every adapter
> neutralises it before display exactly as it does the confirmation content, the
> plan's rationale and a policy's reason (ADR-0042 §4). On the CLI that is
> `interfaces.cli._safe`.

### 9. What this ADR does not decide

> **Normative.** Beyond §§1–8 and §10, this ADR decides nothing. It adds no Protocol,
> registers no tool, designates no seam, adds no setting, changes no method
> signature, and adds no `core` name other than §3's single field. A lane needing
> any of those needs its own change and, where golden rule 5 reaches it, its own
> ADR.

- **Streaming.** This decides a whole answer returned as one result payload.
  ADR-0042 §5's deferred streaming façade method stays deferred, and the hub-side
  half of streaming is milestone 18 of #1312 — where the correlation id's reserved
  second job (ADR-0084 §3) is the affordance to spend.
- **Hub-owned intent routing** (`ask` → typed operation). Deferred on #1312 and
  still named on #1230.
- **The plan-driving stage** (#242), and the overall per-request deadline
  ADR-0042 §3 parks with it.
- **The planner's non-empty `steps` requirement** (#1315). The answer sits beside
  the plan, so this ruling does not depend on relaxing it, and relaxing it is a
  `planning/` change and a different lane.
- **Whether the composed answer joins the episode the turn captures** (#1314).
  That is `track:memory` ground — ADR-0074 §3's capture and ADR-0162's premise
  about whose turns are recorded — and deciding it inside a conversation-track ADR
  would rule on a track that is not this one.
- **Which model answers, and the prompt's own text.** The prompt is
  `orchestration`'s to write. `benchmarks/memory/answer.py` holds a working
  answering prompt today, built on `orchestration.conversations.BELIEF_KINDS` and
  ADR-0158's episodic supplement; the implementing lane may take its shape, but a
  benchmark harness is not a contract on the product path and this ADR adopts
  none of it.
- **What the CLI's turn rendering should look like** beyond §6's floor and §8's
  neutralisation.

### 10. What the implementing lane owes

Mostly a checklist of obligations already marked above, so the lane's brief can be
short. It owes: §3's single field with §4's two-directional validator; the
composing stage in `orchestration` per §2 and its composition-root wiring; §5's
inputs actually threaded to it; §7's `PROTOCOL_VERSION` bump and note in the same
change; §8's three clauses; §6's rendering floor honoured in `interfaces/cli.py`;
and the pipeline stage list in `orchestration`'s module docstring amended per §1.
That it may not touch `core/protocols.py` follows from §2 rather than being added
here. One obligation is genuinely new and is therefore marked:

> **Normative.** In the same change as the field, the implementing lane lands tests
> pinning: §4's invariant in both directions; §5's construction obligations — that
> the stage is handed the undriven steps and each driven step's disposition, status
> and failure, and that `memory_degraded` reaches it; §6's guarantee under a
> **deliberately contradictory provider**, a fake whose completion claims an action
> the step account records as `NO_CAPABLE_TOOL` and again as `DENIED`, asserting
> that the outcome's disposition and the rendered step account are unchanged by
> what the reply says; and §8's `ModelResponseError` on a blank completion.

The contradictory-provider test is the one that matters most and is the easiest to
omit, because every natural test of a composing stage uses a fake that cooperates.
A cooperating fake cannot distinguish a design whose guarantee is structural from
one whose guarantee is a hope about the prompt — which is exactly the distinction
§5 and §6 were rewritten to make.

## Consequences

- **The assistant answers.** A request that needs no tool produces prose composed
  from the model, the retrieved memories and the assembled context, returned on the
  connection the ask arrived on. Milestone 17's exit test becomes runnable from the
  CLI, which #1312 makes the exerciser of every exit on this track.
- **Three docstrings stop being aspirational.** `TurnOutcome.capture_degraded`'s
  "the answer is still the answer", `TurnResult.memory_degraded`'s "an
  unpersonalised answer", and the CLI's "so this answer is generic" all become true
  of a thing that exists.
- **The wire is cheap and the version is not.** No module under `wire/` changes but
  the version constant, and `PROTOCOL_VERSION` moves — to whatever the next number
  is when the lane lands, deliberately not named here, since other lanes may move it
  first and a number written into a ratified document cannot be corrected in place.
  What it buys is an exact-match handshake refusal for a half-upgraded pair, which
  is what that constant is for (ADR-0084 §3).
- **`NO_CAPABLE_TOOL` stops being the user's whole experience and stays the user's
  information.** §6 keeps the line on screen. Until #1315 is picked up it will
  appear under conversational answers, because the planner must still invent a
  capability for a request that needs none — visible, honest, and mildly ugly.
- **The composing stage is a second model call per turn**, after the planner's. It
  costs latency and tokens on every turn, including turns that drove a tool
  successfully. That is the price of the product, and it is stated rather than
  discovered.
- **A model now writes text the user reads as the assistant's own voice.** Every
  prior model output in the product path was parsed — a plan, a proposal, a
  distillation — and checked by deterministic code before it meant anything. §5 and
  §6 are what bound this one: the account of what happened stays the engine's, and
  the prose sits beside it.
- **Revisit if** streaming graduates from deferred to decided (milestone 18), which
  makes "one answer in one result payload" the thing to amend; or if a second
  consumer of composed answers appears with different inputs, which is when a
  Protocol for the stage — declined in §2 for having one implementation and one
  consumer — earns its triad.

## Alternatives considered

**Register a `reply` tool.** Give the registry a tool advertising an `answer`
capability, and let the planner's step select it like any other. *Rejected.* It
routes the answer through `ToolInvoker.invoke`, ADR-0148's per-call machinery and
ADR-0021 §5's floor, which means asking the user to authorise the assistant
talking to them; it obliges an ADR-0016 declaration with a non-empty `discloses`
set for a call that discloses nothing to anyone; and it makes ADR-0154 §1's
designated-seam question live on a path that never leaves the process. It also
buys the one thing this design refuses: a `StepExecution` naming a tool and an
approval for a step that is not an action.

**Put the answer in `ActionPlan.rationale`, or in `StepExecution.output`.**
*Rejected* in §3, each against its own documented meaning and, for `output`,
against a validator that already refuses it.

**Copy `NotificationCandidate`'s two-tier shape — a `summary` and an optional
`detail`.** *Rejected.* That shape exists because a notification must fit one line
on a lock screen before the user decides to expand it (ADR-0130's perishability
argument). An answer to a question the user just asked is already expanded; they
asked for it. Splitting it would oblige the composing stage to invent a headline
for prose nobody needs a headline for, and would put two text fields on the wire
where clients must decide which to show.

**Let the adapter compose the answer from `TurnOutcome`.** The CLI already holds
the plan, the memories and the context; it could call a model itself. *Rejected*
by golden rule 3 outright — that is business logic in an interface — and by the
hub-and-spokes stance behind ADR-0083/0084: every spoke would then need a model
provider, a prompt and a key, and two spokes would answer the same question
differently. The intelligence belongs to the hub.

**Rule the reply out of scope until the tool seam is finished.** The status quo,
stated as a choice. *Rejected.* It rests on the misreading §1 corrects — the reply
does not touch that seam — and it leaves the pipeline's terminal stage waiting on
work that is unrelated to it. VISION's own diagnosis is that a useful assistant
"must do more than answer questions"; it does not say it may do less.
