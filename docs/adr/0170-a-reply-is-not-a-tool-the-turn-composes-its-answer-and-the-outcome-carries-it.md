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
  is prose only. §3 is the surface: **two fields on `TurnOutcome`**. The
  implementation is a separate lane against this ADR once it is merged (golden
  rule 5, ADR-0015 §5).
- **Amends no ADR and supersedes none, and the case worth arguing is ADR-0085 §4.**
  That section's Group A table lists `TurnOutcome`'s four fields, and after this
  ADR the tree has six — so the question is whether adding a field to a type
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
  boundary three, ratified by ADR-0124 §1 — and the answer **does** carry user data
  the request did not. "What do you know about me?" comes back as "you prefer
  hiking", composed from accumulated memory; that is the milestone's whole point and
  it needs no minimising. ADR-0124 §1 authorises the hub's transport to an enrolled
  device as such, and the permission does not turn on the payload being derivable
  from the request that asked for it.
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

### 2. The stage lives in `orchestration`, and consumes exactly one contract

> **Normative.** The composing stage lives in `ai_assistant.orchestration` and
> reaches the model through the injected `ModelProvider` contract. It is not in
> `interfaces/` (golden rule 3 — no business logic in an adapter), not in `models/`
> (golden rule 4 leaves that the provider wrapper), and not in `planning/`, whose
> product is an `ActionPlan`.

> **Normative.** The stage adds **no Protocol and no member to one**.
> `ModelProvider.complete` is the whole of what it consumes, it is already
> ratified, and no triad is owed because no Protocol is new (`CONTRIBUTING.md` →
> "Adding a Protocol").

> **Normative.** The stage consumes **no `ContextProvider` and no `MemoryStore`**.
> Its context and its memories are the ones the turn already assembled, reaching it
> as the `TurnResult` the turn produced — `goal`, `context`, `memories`, `plan` and
> `memory_degraded` — together with the `StepOutcome`. It performs no second
> context assembly and no second retrieval.

> **Normative.** The stage's `ModelProvider` is injected into it explicitly by the
> composition root, an ADR-0028 §4 obligation that creates no new contract. No lane
> obtains one by reaching through `Engine`'s collaborators — `Engine.__init__`
> receives no `ModelProvider` and no `ContextProvider`, and reaching a concrete
> subsystem's internals to find one is the import golden rule 1 forbids.

`ModelProvider.complete` is already the right shape and says so itself: "Produce
the assistant's next message given the conversation so far", returning "The
assistant's reply as a `Message`". ADR-0066 named the seam's precondition — a
completion request must end awaiting an answer — and a composing stage is the
first caller in the product path for which that description is literal rather than
a metaphor for planning. `ConsolidationStage` is the precedent for an
`orchestration` stage holding an injected `ModelProvider`; it takes one today.

**Where the model reaches the turn path today is worth stating, because it is not
where a reader assumes.** `Engine.__init__` takes a `MemoryStore` but no
`ModelProvider` and no `ContextProvider`: the context provider is `LearningLoop`'s,
and the model reaches the loop only *through* the injected `Planner`. So the
composing stage's provider is a genuinely new injection at the composition root
rather than a collaborator already in hand — which is why the clause above says so
rather than leaving a lane to discover it and reach downward for one.

> **Normative.** The composing stage sets no execution status, writes no
> `StepStatus`, transitions no step and produces no `ActionPlan`. VISION §7's rule
> that model output never sets execution status is untouched, and no lane cites
> this ADR toward relaxing it.

That clause exists because VISION §7 is the first objection a careful reader
reaches for, and it is answered rather than waved at: the stage reads the outcome
deterministic code committed and renders prose about it. Nothing flows the other
way.

### 3. The contract surface: two fields on `TurnOutcome`, and nothing else

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

> **Normative.** `TurnOutcome` gains exactly two fields: `reply`, typed
> `NonBlankEncodableText | None` and defaulting to `None`, carrying the
> natural-language answer the turn composed; and `reply_degraded`, a `bool`
> defaulting to `False`, saying whether composing that answer **failed** on a turn
> that otherwise ran. `reply` is the only place an answer is carried.

`NonBlankEncodableText` rather than `EncodableText`, because §4 gives `None` a
precise meaning and a blank string would be a third state meaning the same thing
less legibly — the reasoning `NotificationCandidate.summary` already applies to
the one line a user is told.

**`reply_degraded` is the third of a set, not a new idea.** `TurnResult` already
carries `memory_degraded` for a retrieval that failed and `TurnOutcome` already
carries `capture_degraded` for a record that could not be written. Each says the
same kind of thing: a late stage failed, the turn is still worth returning, and the
user is told rather than left to infer it. §8 is where composition earns its own,
and the argument there is `capture_degraded`'s own — "failing would throw away
[what] the user already has".

> **Normative.** Each field's docstring names this ADR as the decision that added
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

> **Normative.** `reply` is `None` on exactly three shapes and non-`None` on every
> other outcome the two turn calls return:
>
> - a pass whose step reached `Disposition.AWAITING_CONFIRMATION`, where what the
>   user must answer is the `Confirmation` the adapter renders and relays;
> - a pass whose `turn` is `None` — a resume driven from a **recovered** park
>   (ADR-0052 §3) — where context and memories were never persisted and there is
>   nothing to compose from; and
> - a pass on which composition **failed** (§8), which is the one of the three that
>   sets `reply_degraded`.

> **Normative.** `reply_degraded` is `True` on that third shape and on no other. It
> is never `True` beside a non-`None` `reply`, never `True` on a park, and never
> `True` where `turn` is `None` — so a client can tell "no answer was owed" from
> "an answer was owed and could not be composed" from the value alone.

> **Normative.** The implementing lane states both invariants as a
> `model_validator(mode="after")` on `TurnOutcome`, in **both** directions, as
> `StepOutcome._confirmation_matches_disposition` states its own.

Both directions, for that validator's own reason. A silent `None` on a turn that
ran is an answer the user never got and nobody can point at a contract violation
for; a `reply` beside a parked confirmation is prose competing with a yes/no
question the user must answer, and the prose is what they will read.

**The flag is what makes the third shape legible.** Without it, a composition
failure would be a `None` no client could tell from the other two — which is the
argument for making such a failure *raise* instead, and it is a good argument
against a bare `None` rather than against this one. The flag distinguishes the
case; §8 is where raising is weighed on its own merits and declined.

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
> `Disposition`, its durable `StepStatus`, its `SkipReason` where it has one, and
> its `StepFailure.kind` where a tool produced one. Withholding any of those from
> the stage is a defect of this decision.

Every value in that list is a **closed vocabulary this system owns** — four enums,
each exhaustively enumerated in `core/types.py`. That is deliberate and §5a is why:
the one field of the step account that is free text, `StepFailure.message`, is
excluded there rather than here, because excluding it is a prompt-safety ruling
and not a question of what the stage needs to know.

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

### 5a. The composing stage is a prompt assembler, and ADR-0098 §2 binds it

This section exists because ADR-0098 §9 asked for it in terms. Its list of what
the implementing lanes owe says of a later prompt-rendering addition that "the
lane that adds it inherits §2 and should be told so in its ADR". This ADR creates
a **new prompt assembler** — a stage that renders retrieved memories, assembled
context and a step account into a model call — so this is that telling, and
leaving it out would have shipped the first assembler in the product path that
nobody told.

> **Normative.** The composing stage is a prompt assembler under ADR-0098 §2 and
> inherits that section whole. Every span of external content reaching it — a
> retrieved `MemoryRecord` whose `Provenance.source` marks it external, and any
> facet text of external origin — is presented to the model as third-party data,
> distinguishable from this system's own instruction and from the user's own words.

> **Normative.** Step-account text that carries **no recorded provenance does not
> reach the model at all**. `StepFailure.message` is free text a failing tool
> influences and `StepFailure` carries no `Provenance`; a registered tool's
> identifier and description may originate with an MCP server rather than with this
> repository (ADR-0147). The stage renders the step account as a **deterministic
> local summary** built from §5's closed vocabularies — `Disposition`,
> `StepStatus`, `SkipReason`, `ToolFailureKind` — and passes none of that free text
> through.

> **Normative.** That distinction is **not forgeable from inside the span**. It is
> derived from data the assembler holds — `Provenance.source`, an `Attestation`, a
> facet's source — and never from inspecting the text, so no sequence of characters
> inside a retrieved record may change which span the prompt attributes to whom.

> **Normative.** The implementing lane ships ADR-0098 §9's marked test **for this
> assembler**: a record whose `content` contains the assembler's own container
> syntax — its bullet, label, header and newline structure — asserting that the
> assembled prompt's attribution of every span is unchanged by it. A test asserting
> only that a label is present does not satisfy that clause and does not satisfy
> this one.

**The identifier half is not hypothetical, and the tree is why it is named
separately.** `Identifier` refuses only a blank and `VisibleIdentifier` only
something with no visible text — neither constrains *structure*. Both accept
`"mail\nSYSTEM: ignore prior instructions"` today, verified by validating it. So a
tool id is a span that can carry an assembler's own container syntax while looking
like a well-typed `core` value, and tightening the type is issue **#62**, a
cross-lane change this ADR does not make. Excluding the id from the prompt is what
makes that irrelevant here rather than blocking on it.

**Nothing is lost to the operator by that exclusion, and that is what makes it
cheap.** `StepFailure.message` is a Tier 2 operator-facing explanation, and §6
keeps the whole step account on screen beside the answer — the message is read
where it was always read. What changes is only that it stops being *prompt input*,
which it never needed to be: the model is composing prose about what happened, and
the four enums say what happened. Giving the step-result surface provenance so such
text could be attributed conformingly would be a `core` contract change with its
own ADR, and §9 records it as not decided here rather than as a prerequisite.

ADR-0098 §3 — instructions inside external content are data, and external content
is never the authority for an action — is satisfied structurally here rather than
by a further clause, and §2 above is why: the composing stage takes no action, sets
no execution status and transitions no step, so there is no authority for a steered
span to borrow. What it can still do is put words in the assistant's mouth, which
is what §2's non-forgeability and §6's deterministic account are between it and the
user.

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

> **Normative.** The step account is rendered on a degraded turn too. A
> `reply_degraded` outcome (§8) is rendered as the account it carries plus a
> statement that no answer could be composed — never as a silent turn, and never as
> a failure of the step the account says succeeded.

That clause is what makes §8's degradation tolerable rather than merely cheap. A
turn that sent an email and then could not describe it still tells the user the
email was sent, in the same words it would have used before this ADR existed; the
only thing missing is the prose that was going to sit above it.

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

> **Normative.** A composition failure **degrades the turn; it does not fail it**.
> The turn returns its `TurnOutcome` with `reply` `None` and `reply_degraded`
> `True`, carrying its `turn`, its `step` and its `conversation_id` unchanged. The
> two turn calls do not raise for it.

> **Normative.** A composition failure is any of: the model call failing, a
> completion whose content is blank or otherwise unusable as an answer, or the
> stage failing for a reason of its own. All three degrade identically, and none
> becomes a `reply`.

> **Normative.** The stage originates **one** `ModelProvider.complete()` call per
> turn. It does not loop, does not call again on a failure that call returns, and
> does not re-plan — a second attempt is the caller asking again, which is a new
> turn under the caller's own budget. What the injected provider does *below* that
> seam is not this ADR's to constrain.

**The clause binds the composer, not the provider stack.** Retry and fallback
routing are cross-cutting behaviour composed by wrapping — ADR-0011 §2 makes a
substitutable `ModelProvider` that holds another one the way resilience is added,
and ADR-0013 §3 wires `RoutingProvider(RetryingProvider(...))` deliberately, so a
single `complete()` may already make several vendor calls before it returns. A
stage forbidden to "re-route" would either contradict a conforming provider or
have to inspect what it was injected, which is the coupling ADR-0011 §2 exists to
avoid. What §8 rules out is the *stage* looping: no second `complete()` of its
own, no re-planning, no second bite at a turn the caller can simply ask again.

> **Normative.** The two turn calls never surface a pydantic `ValidationError` from
> `TurnOutcome` construction to a caller.

**Degrading rather than raising is `capture_degraded`'s argument, and the case that
settles it is a side effect that already happened.** A turn can approve a
non-idempotent tool (`Idempotency.NONE`), execute it successfully, commit its
`StepExecution` durably to `plans.db` — and only *then* have composition fail. If
the turn raised there, the caller would hold an error and no outcome: no
`conversation_id`, no step account, no record of the send in the value they were
given. The natural recovery from an error is to ask again, which re-plans and can
perform the effect a second time, and `resume` is not a way back either because
its continuation is consumed once the step resolved. Raising would therefore turn
a *successful, irreversible* action into an invisible one, against ADR-0014's
whole reason for keeping execution state separate from the plan — so that recovery
is loading what happened rather than redoing it.

That is `capture_degraded` reasoning applied one stage later: "failing would throw
away an answer the user already has because the record of it could not be written."
Here the thing already had is the *action*, and what could not be written is the
prose about it. The prose is the part worth losing.

**The blank-completion path lands in the same place, and it is reachable on a
conforming provider.** `Message.content` is `EncodableText`, which admits the
empty string, so a provider may return an assistant message with no content at
all. That call did not *fail*, and §3's `NonBlankEncodableText` cannot hold the
result, so a naive implementation would raise a bare pydantic `ValidationError`
out of the engine. The second clause above makes it a degradation instead, which
is both classified and identical to every other way composition can come back
empty-handed.

**Why the blank check is not pushed inside the model seam, where routing could act
on it.** That is the better place, and this ADR declines it on scope rather than on
merit. `ModelResponseError` is `routable = True` — "another may answer usably" —
and `RoutingProvider` fails over on exactly that flag. But a blank completion is
*contract-valid*: `Message.content` is `EncodableText`, the conformance suite
asserts only that a `str` comes back, so the router sees a successful call and
stops, and no fallback is ever attempted. Obliging every `ModelProvider` to raise
instead would be a **new postcondition on `ModelProvider.complete`** — a Protocol
change, which golden rule 5 puts behind its own ratified ADR and which
`CONTRIBUTING.md` → "Adding a Protocol" moves together with its conformance suite
and canonical fake. That is a different lane and a different subsystem.

It is also **not a defect this decision introduces**: `ModelBackedPlanner` has the
same exposure today, a blank completion reaching `_require_steps` with no route
left to try. Filed as **#1324**, with what a lane picking it up would weigh. Until
then a degraded turn is the honest report: it claims no failover it cannot
deliver, and it hands the caller the outcome rather than an exception.

> **Normative.** A composed answer is engine-supplied text, and every adapter
> neutralises it before display exactly as it does the confirmation content, the
> plan's rationale and a policy's reason (ADR-0042 §4). On the CLI that is
> `interfaces.cli._safe`.

### 9. What this ADR does not decide

> **Normative.** Beyond §§1–8 — §5a included — and §10, this ADR decides nothing.
> It adds no Protocol, registers no tool, designates no seam, adds no setting,
> changes no method signature, and adds no `core` name other than §3's two
> fields. A lane needing any of those needs its own change and, where golden rule 5
> reaches it, its own ADR.

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
- **Whether the step-result surface should carry provenance**, so that a tool's
  own failure text could be rendered into a prompt under ADR-0098 §2 instead of
  excluded by §5a. That is a `core` contract change and needs its own ADR; §5a's
  exclusion is what makes this ADR not depend on it.
- **Whether a blank completion should be refused inside the model seam** (#1324),
  which is a `ModelProvider` postcondition change and so its own ADR under golden
  rule 5. §8 keeps this ADR's refusal above the seam and non-routable, and changes
  no Protocol.
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
short. It owes: §3's two fields with §4's two-directional validator; the
composing stage in `orchestration` per §2 and its composition-root wiring; §5's
inputs actually threaded to it; §5a's non-forgeable attribution; §7's
`PROTOCOL_VERSION` bump and note in the same change; §8's clauses; §6's rendering
floor honoured in `interfaces/cli.py`; and the pipeline stage list in
`orchestration`'s module docstring amended per §1. That it may not touch
`core/protocols.py` follows from §2 rather than being added here, and it is what
keeps this one lane in one subsystem plus `core`'s two fields. One obligation is
genuinely new, and two are therefore marked:

> **Normative.** In the same change as the fields, the implementing lane lands tests
> pinning: §4's invariants in both directions, `reply_degraded` included; §5's
> construction obligations — that the stage is handed the undriven steps and each
> driven step's disposition, status, skip reason and failure kind, and that
> `memory_degraded` reaches it; §5a's ADR-0098 §9 test, **and** that no
> provenance-less step-account text reaches the assembled prompt — asserted over a
> `StepFailure.message` **and** over a syntax-bearing `tool_id`, one carrying the
> assembler's own container structure, each shown absent from the prompt; §6's
> guarantee under a **deliberately contradictory provider**, a fake whose completion
> claims an action the step account records as `NO_CAPABLE_TOOL` and again as
> `DENIED`, asserting that the outcome's disposition and the rendered step account
> are unchanged by what the reply says; and §8's degradation on a failing composer
> and on a blank completion alike.

> **Normative.** §8's post-side-effect case is pinned by a test of its own: a
> successfully executed `Idempotency.NONE` tool whose step commits, followed by a
> composer that fails, asserting that the call **returns** rather than raises, that
> the returned outcome carries the step account and `conversation_id`, that
> `reply_degraded` is `True`, and that nothing re-executes.

The contradictory-provider test is the one that matters most and is the easiest to
omit, because every natural test of a composing stage uses a fake that cooperates.
A cooperating fake cannot distinguish a design whose guarantee is structural from
one whose guarantee is a hope about the prompt — which is exactly the distinction
§5 and §6 were written to make.

## Consequences

- **The assistant answers.** A request that needs no tool produces prose composed
  from the model, the retrieved memories and the assembled context, returned on the
  connection the ask arrived on. Milestone 17's exit test becomes runnable from the
  CLI, which #1312 makes the exerciser of every exit on this track.
- **Three docstrings stop being aspirational.** `TurnOutcome.capture_degraded`'s
  "the answer is still the answer", `TurnResult.memory_degraded`'s "an
  unpersonalised answer", and the CLI's "so this answer is generic" all become true
  of a thing that exists.
- **The turn path carries three degradation flags rather than two**, and a client
  now checks `reply_degraded` beside `memory_degraded` and `capture_degraded`. That
  is a cost — three booleans is where a reader starts wanting one structured
  report — and it is paid deliberately: each names a different stage, and collapsing
  them would tell a user "something went wrong" where today they are told which
  thing. A fourth would be the trigger to revisit the shape rather than add it.
- **A turn can now succeed at acting and fail at speaking.** §8 makes that a
  degradation, so an irreversible side effect is never hidden behind an exception
  whose only retry would repeat it; §6 keeps the step account on screen so the user
  still learns what happened. The user experience of that turn is worse than a
  normal one and much better than a lie or a double send.
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

**Raise on a composition failure instead of degrading.** One field rather than two,
and a caller that cannot mistake a failed turn for a successful one. *Rejected*
in §8. It is correct only while the turn has done nothing irreversible, and the
turn that most needs an answer is the one that just acted: a successfully executed
`Idempotency.NONE` tool whose step committed, followed by a failing composer, would
reach the caller as an exception carrying no outcome — no `conversation_id`, no
step account, no record of the send — whose natural retry re-plans and can perform
the effect twice. `resume` is no way back, because the continuation is consumed
once the step resolved. The corpus had already chosen degradation for the same
shape one stage earlier, in `capture_degraded`, and for the same reason.

**Rule the reply out of scope until the tool seam is finished.** The status quo,
stated as a choice. *Rejected.* It rests on the misreading §1 corrects — the reply
does not touch that seam — and it leaves the pipeline's terminal stage waiting on
work that is unrelated to it. VISION's own diagnosis is that a useful assistant
"must do more than answer questions"; it does not say it may do less.
