# 197. An ask reaches the hub's own operations through a routing stage, and a routed operation is never re-read

- Status: Proposed
- Date: 2026-08-27
- **This is `track:conversation` (#1312) milestone 26's ruling**, and it decides the
  line both #1312 and #1230 have carried as deferred since ADR-0170 §9 named it:
  *`ask` → typed operation, one-directional — a typed operation is never re-read —
  with its own confirm rule for non-read-only operations, distinct from the tool
  seam.* The milestone's exit test is on #1623. Refs #1623, #1312, #1230.
- **It decides a `core` surface and is therefore reviewed under both lenses.**
  `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a change
  contract-surface "when it is the ADR deciding that surface", prose-only though
  this PR is. §8 is the surface: one field on `TurnOutcome`, four new `core/types.py`
  names, and one new Protocol in `core/protocols.py`. The implementation is separate
  lanes against this ADR once it is merged (golden rule 5, ADR-0015 §5).
- **It partially supersedes ADR-0170 §4** — that section's second `None` shape and
  its two clauses stated in the `turn is None` direction, exactly as far as they
  reach an outcome carrying §8's `routed` member, and no further. §13 states the
  record and the reasoning; §8 states the replacement invariants.
- **It amends ADR-0052 §1** by a reading and not by a decision: that section's
  "the confirmations a user may still answer" is true of every confirmation it
  ranges over and is not true of §7's routed park, which holds no plan state for
  §1's algorithm to recover. §13 states the record.
- **`AssistantEngine` gains no method and the browser's reach does not move.**
  ADR-0177 §1's enumeration of thirty already contains `converse`,
  `converse_streaming` and `resume`, and this ADR admits no operation to it and
  removes none. ADR-0186's own durable form of that rule — "a method on
  `AssistantEngine` is outside the browser's reach until an ADR puts it inside" —
  is the reason §9's trail is unreachable from a browser rather than a gap in it.
- **Nothing here is cited toward the `tools/` egress seam.** ADR-0154 §2's clauses
  stand whole, ADR-0017 §3's fourteen conditions are neither discharged nor
  relaxed, no tool is registered and no destination is approved. §1 and §7 argue
  that a routed operation never reaches that seam at all, which is the opposite of
  a claim about it.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-27**, the
  durability form ADR-0100 established.

## Context

### The engine can reach the world and cannot reach itself

`AssistantEngine` carries **thirty-nine** operations. One of them, `converse`, runs
the pipeline ADR-0170 completed: intent understanding, context assembly, memory
retrieval, planning, tool selection, permission checking, execution, and the
terminal composing stage. Every stage between planning and composition is about
reaching the **world**, through `tools/`.

None of them can reach the other thirty-eight operations. `ModelBackedPlanner`
emits a `capability` — an open, unvalidated vocabulary (ADR-0047 §5) — which
`ToolRegistry.find` resolves against registered tools and nothing else. There is
no capability that names `forget`, and ADR-0170 §1 forbids inventing one:

> **Normative.** Composing a natural-language reply to the user and returning it as
> the result of the request that asked for it is **not** a tool invocation.

The reasoning there was about replies, but its refusals reach further. Routing a
hub operation through `ToolRegistry.find`, `ActionPolicy.decide` and
`ToolInvoker.invoke` would write a `StepExecution` naming a tool that does not
exist and an approval that was never given — the falsehood-in-durable-state
ADR-0170 §3 refused for `StepExecution.output`, arriving by a different door.

So "forget that I like jazz" is planned as an invented capability, skipped with
`SkipReason.NO_CAPABLE_TOOL`, and ADR-0170 §5 obliges the composed reply to say
the assistant did not do it. That is honest and it is the whole of what happens.
VISION's *In Control* verbs — inspect, correct, restrict, delete — exist only as
CLI subcommands and browser buttons.

### Two doors to one surface, and only one of them is a sentence

The gap is not that the operations are missing. `forget`, `grant`, `revoke`,
`answer`, `recent_reads`, `spend_totals` are all on the promoted surface, all
reachable from the CLI (ADR-0084) and twenty-eight of the thirty from a browser
(ADR-0177 §1). What is missing is the door a person actually uses: saying it.

This is why the deferred line calls the destination a *typed operation* rather
than a tool. The work is not to give the assistant a new capability; it is to let
one sentence select an operation the surface already declares, resolve the one
argument that sentence implies, and — where the operation writes — put what it is
about to do in front of the user before it does it.

### What the deferred line already decided, and what makes each clause hold

Three clauses have been on the record since ADR-0170 §9, and each is load-bearing
rather than decorative.

**Distinct from the tool seam**, because a `forget` is not egress. ADR-0124 §1's
live rule names three boundaries — `models/`, the designated `tools/` seam, and
the hub's transport to an enrolled device. A routed `forget` crosses none of them:
it reads and writes the hub's own stores in the hub's own process. Putting it
through ADR-0148's machinery would demand a canonical destination set and a
payload description for a call with no recipient (§8's two floors), and would make
every hub operation a registered tool.

**One-directional — a typed operation is never re-read.** The result of a routed
operation is the user's own data: their beliefs, their read trail, their permission
decisions. Feeding it back into a prompt in the same turn puts the control surface
in front of the model and lets one ask become a chain of operations. The
deterministic result is rendered **beside** the reply, the way ADR-0170 §6 renders
the step account beside it, and the composing stage is told only that an operation
ran and which closed-vocabulary outcome it reached.

**Its own confirm rule.** `forget` destroys; `grant` widens; `revoke` and `answer`
write. ADR-0073 §5 already rules the shape for the destructive one — "the surface
renders the belief it is about to destroy … and takes the user's confirmation
before deleting" — and the reason given there is the reason here: *a person cannot
consent to destroying something they were not shown.* What routing adds is that a
**model** chose the subject, which makes showing it before acting the whole of the
mitigation rather than a courtesy.

### What the tree will and will not carry, read rather than assumed

Four facts were read off `origin/main` before this decision was written, because
each of them rules out a design that looks obvious from the deferred line alone.

`TurnResult` requires a `plan`. Its five fields are `goal`, `context`, `memories`,
`plan` and `memory_degraded`, all required but the last. So a pass that does not
plan cannot produce one, and `TurnOutcome.turn` is `None` on such a pass — which
ADR-0170 §4 then forbids to carry a `reply`. §1 and §8 are where that is faced.

`Confirmation`'s content members are **tool-shaped**: `tool_id`,
`tool_description`, `parameters`, `reason`, plus `token` and ADR-0178 §1's
`egress`. There is no tool and no policy ruling behind a routed act, so three of
those four have nothing truthful to hold.

`AssistantEngine.resume` takes `approved: bool`. A confirmation is a yes/no
question and cannot select among candidates, whatever the card renders.

`ADR-0052 §1`'s recovery walks `plans.active_executions()` and, for each step in
`AWAITING_APPROVAL`, recovers the pending `CONFIRM` from the audit trail. A routed
park has no execution, no step and no `PermissionDecision`, so there is nothing
for that algorithm to find.

## Decision

### 1. The pipeline gains a routing stage, it runs first, and a routed ask ends there

> **Normative.** The request pipeline gains one **operation-routing stage**, and it
> is the **first** stage of the pipeline, ahead of intent understanding. Given the
> user's utterance and nothing else, it either names one operation of §3's
> vocabulary together with the one query that operation's argument is resolved
> from, or it **declines**.

> **Normative.** A declined route is not a failure and is not reported as one. The
> pass proceeds through the pipeline exactly as it does today — intent
> understanding, context assembly, memory retrieval, planning, tool selection,
> permission checking, execution, composition — and the outcome it returns carries
> no trace of the routing stage having run.

> **Normative.** A route that is **taken** ends the pipeline there. No goal is
> minted, no context is assembled, no memories are retrieved, no plan is made or
> persisted, no step is driven, no capacity slot is taken and no `ToolRegistry`,
> `ActionPolicy` or `ToolInvoker` is reached. The composing stage still runs, on
> §6's inputs.

> **Normative.** **One ask performs at most one routed operation, by construction.**
> The routing stage is entered once per `converse`, `converse_streaming` or
> `resume` pass, and no clause of this ADR, and no later ADR citing it, permits a
> routed operation's result to select a second operation within the same pass.

> **Normative.** The implementing lane amends the pipeline's stage list in
> `ai_assistant.orchestration`'s module docstring to name the routing stage in its
> position, as ADR-0170 §1 obliged for the composing stage and for its reason.

**Running first is what makes a routed ask cheap and what makes it safe.** Cheap,
because the two stages a routed ask does not need — context assembly and memory
retrieval — are the two most expensive things `LearningLoop.respond` does, and a
routed ask skips both along with the planner's model call. Safe, because a router
that has not yet read the store cannot be steered by what is in it: §4 is where
that becomes a clause rather than an accident.

**The cost is stated rather than discovered: a *declined* route is one extra model
call on every turn that is not routed.** An ordinary ask costs two model calls
today — the planner's and the composer's — and costs three after this. That is
paid on the common case to buy the uncommon one, which is a genuine objection and
is answered in Alternatives considered, where folding the router into the planner's
envelope is weighed and declined on placement rather than on price.

**Ending the pipeline is what "one-directional" means at the pipeline level.** A
routed ask does not route *and then* plan; there is no fall-through after the
operation runs and no second bite. That is the structural half of §6 — the model
cannot chain, whatever it is shown — and it is why §6 needs no prompt to enforce
it.

### 2. The stage lives in `orchestration`, and consumes exactly one contract

> **Normative.** The routing stage lives in `ai_assistant.orchestration` and reaches
> the model through the injected `ModelProvider` contract. It is not in
> `interfaces/` (golden rule 3), not in `models/` (golden rule 4), and not in
> `planning/`, whose product is an `ActionPlan`.

> **Normative.** The stage adds **no member to `ModelProvider`** and no Protocol for
> itself. `ModelProvider.complete` is the whole of what it consumes at the model
> seam, and no triad is owed for the stage (`CONTRIBUTING.md` → "Adding a
> Protocol"). §9's trail Protocol is a separate surface and owes its own triad.

> **Normative.** The stage performs the routed operation by calling the engine's own
> implementation of the named operation. It does not reach into a store the engine
> holds to perform an operation itself, and it composes no operation out of two.

`planning/` is refused for ADR-0170 §2's own reason, applied to a different
product: that section put the composing stage outside `planning/` because a reply
is not an `ActionPlan`, and a routed operation is not one either. There is a second
reason here that ADR-0170 did not need. The routable vocabulary is a subset of
`AssistantEngine`'s own façade; a planner that knew it would be a subsystem
reaching for the engine's surface, which golden rule 1 forbids and which ADR-0047
§5 already declines in the smaller case ("it does **not** check a capability
against any tool registry, because that would import the `tools` subsystem").

The third clause is the one worth stating rather than assuming. "Perform the
operation" could mean *call the façade method* or *do what the façade method does*,
and only the first keeps one implementation of `forget`. The second would put a
second `MemoryStore.delete` call site behind a different set of preconditions,
which is how two doors to one operation stop behaving the same way.

### 3. The routable vocabulary: eleven operations, each tagged, and the rule that widens it

> **Normative.** `core/types.py` gains `RoutableOperation`, a `StrEnum` whose members
> are the operations an ask may be routed to. Its members are exactly these eleven,
> named for the `AssistantEngine` operation each routes to:
>
> - **read-only** — `questions`, `recent_reads`, `recent_invocations`,
>   `recent_decisions`, `standing_grants`, `spend_totals`;
> - **confirm-owed** — `forget`, `answer`, `grant`, `revoke`, `forget_question`.

> **Normative.** An operation is **read-only** exactly when performing it writes
> nothing durable and destroys nothing, and **confirm-owed** otherwise. The tag is a
> property of the operation, not of the turn, the utterance or the user: no
> setting, adapter, policy or later ADR makes a confirm-owed operation route
> without §7's confirmation, and no `--yes` idiom removes the render that precedes
> it (ADR-0073 §5).

> **Normative.** The direction of a write does not change its tag. `revoke` narrows
> what the assistant may read and is still confirm-owed, because what §7 guards is
> not the risk of the operation but the fact that a **model** selected it and its
> subject from a sentence.

> **Normative.** No routable operation takes a `SecretValue`, and
> `connect_account`, `reprovision_account` and `disconnect_account` are outside the
> vocabulary permanently, not pending a widening. No routable operation is
> `converse`, `converse_streaming` or `resume`.

> **Normative.** **The widening rule.** A later lane may add a member to
> `RoutableOperation` without an ADR of its own exactly when the operation
> satisfies all five of: (i) it is a member of the promoted `AssistantEngine`
> surface; (ii) performing it reaches no egress boundary — no `ToolRegistry`, no
> `ToolInvoker`, no `EgressDestination`, no credential; (iii) its arguments are
> either none, or resolvable by §5's deterministic lookup from a router-named
> query; (iv) it is tagged by the test above; and (v) where it is read-only, its
> result type is already an arm of §8's `RoutedListing`. An operation failing any of
> the five is outside the vocabulary until an ADR puts it inside.

> **Normative.** A lane exercising the widening rule states, in the ADR its own
> change already owes, which of the five conditions each added member satisfies and
> how. Adding a member silently does not satisfy this clause.

**Why a starter set rather than every non-egress operation.** Twenty-eight of the
thirty-nine would pass conditions (i) and (ii). What stops them is (iii) and (v):
`set_notification_preferences` takes a whole `NotificationPreferences` object that
no query resolves to; `belief` and `conversation` take an id a user does not say;
`observe` takes an optional conversation and returns an `ObservationReport` no arm
carries. The eleven above are the ones a person says out loud, and the vocabulary
is closed at what has been argued rather than at what would compile.

**`beliefs` is deliberately excluded, and that is the one exclusion a reader will
expect to be wrong.** "What do you know about me?" is milestone 17's ruled exit
test, and it is answered *today* by the composing stage from the memories the turn
retrieved — prose about the user, not a listing of `BeliefSummary` rows. Routing it
would replace a ruled behaviour with a worse one, which is a regression this
decision would have caused rather than a gap it closes. The belief *listing* stays
where it is: `assistant beliefs`, and the browser's control surface.

**`learn` is excluded although VISION names it among the four verbs.**
`AssistantEngine.learn` takes a `FeedbackEvent` — a structured correction with a
kind, a subject and its content — which is not a thing a router extracts from a
sentence under (iii). What a person *says* when correcting the assistant reaches
memory through `answer` on an open question, which is in the vocabulary, and
through the ordinary pipeline otherwise. ADR-0177 §1's third clause already holds
`learn` outside the browser's reach on a related instinct; this decision does not
disturb it either way.

### 4. The router's envelope declines the way the planner's does, and its prompt holds no external content

> **Normative.** The routing stage originates **exactly one**
> `ModelProvider.complete()` call per pass. It does not loop, does not call again on
> a failure that call returns, and takes no repair round. What the injected provider
> does below that seam is not this ADR's to constrain (ADR-0011 §2).

> **Normative.** The router's output envelope has two legal shapes, discriminated
> the way ADR-0176 §1 discriminates the planner's. A **route envelope** carries an
> `operation` key whose value is the `str` value of a `RoutableOperation` member,
> and a `query` key whose value is a string with at least one non-whitespace
> character where §5's lookup needs one and which is absent otherwise. A **decline
> envelope** carries a `no_operation` key whose value is the JSON boolean `true`.
> No other shape is an envelope.

> **Normative.** The `no_operation` marker is the JSON boolean `true` and nothing
> else, tested by type as well as by value for ADR-0176 §1's own reason — an
> implementation written as `marker == True` accepts `1` and `1.0`, because Python's
> `bool` is a subclass of `int`.

> **Normative.** An `operation` value that is not the `str` value of a
> `RoutableOperation` member is **not** a route envelope and is not an error the
> user sees: it is unclassified output, and the pass declines to route. The
> vocabulary is closed at the boundary, and no near-match, prefix, alias or
> case-fold resolves an unknown value onto a member (contrast ADR-0053's alias
> layer, which exists for the planner's deliberately *open* capability vocabulary).

> **Normative.** Anything that is not one of the two legal envelope shapes — a
> malformed reply, an unknown `operation`, a missing `query` where one is needed, a
> `ModelError` out of the call, or a blank completion — is a **decline**. The
> routing stage raises nothing to the caller, degrades no turn, sets no flag on
> `TurnOutcome`, and takes no repair round.

> **Normative.** The routing stage's prompt contains the user's own utterance and
> the closed vocabulary of §3, **and no other content**. It renders no retrieved
> memory, no context facet, no belief, no trail row, no tool identifier or
> description, and no result of any operation.

**A decline that swallows every failure is the right default and it is not the
lazy one.** The three ways the routing stage can fail are: the model declined
deliberately, the model produced something unusable, and the model call failed.
All three mean the same thing operationally — *this pass has no route* — and all
three have the same correct behaviour, which is the pipeline that ran yesterday.
A degradation flag would be a fourth value on `TurnOutcome` that no client could
act on, because there is nothing for a user to do about it; and raising would turn
a model hiccup into a failed ask on a path that has a perfectly good fallback. The
visible consequence is the status quo: an unroutable "forget that I like jazz"
reaches `NO_CAPABLE_TOOL` and ADR-0170 §5's reply says so. That is the failure this
decision improves on, disclosed rather than hidden when it recurs.

**The last clause is why no ADR-0098 §2 assembler obligation is inherited here, and
it is a structural answer rather than an escaping one.** ADR-0098 §2 binds a
prompt assembler to present every span of external content as third-party data,
non-forgeably. The routing prompt assembles **no external content at all**: the
utterance is the user's own words, and the vocabulary is a closed enum this
repository owns. There is no span for an ingested instruction to occupy, so the
obligation is vacuous by construction rather than discharged by a delimiter — the
strongest form of ADR-0098 §2 compliance available, and the reason §1 puts this
stage ahead of retrieval rather than after it. ADR-0098 §2's "the marking is
derived from data the system holds … and never from inspecting the text" is
satisfied trivially: nothing is marked because nothing external is present.

**What that does *not* claim.** Ingested content can still reach the utterance, by
the ordinary route of a user reading something and repeating it. That is a person
choosing to say a sentence, which is exactly what ADR-0098 §2 calls the user's own
words, and §7's confirmation is what stands between a sentence and a destructive
act. No clause here is a guarantee about the content of model output (ADR-0170 §5,
ADR-0176 §7): a conforming provider may route a sentence that wanted no operation,
or decline one that did. §7 bounds the first and §1's fall-through bounds the
second, and both failures are visible.

### 5. The argument is resolved deterministically, and ambiguity is never guessed

> **Normative.** The router names a **query**, never an identifier, and never an
> argument value. The operation's argument is resolved from that query by
> deterministic local code reading the store the operation itself reads, and the
> resolution is a **lookup, not a generation**: every candidate it returns is a
> record that exists.

> **Normative.** A read-only operation of §3 takes no query and resolves no
> argument. It is performed with the promoted surface's own declared defaults, and
> its bound is `DEFAULT_PAGE_SIZE`. It gets no setting of its own, for ADR-0170
> §8's reason applied here: an existing ceiling that already bounds this listing
> everywhere else is the ceiling.

> **Normative.** Where the lookup resolves to **exactly one** candidate, that
> candidate is the operation's argument. Where it resolves to **none**, the route
> ends in `RouteOutcome.NOT_FOUND`, nothing is performed and nothing is confirmed.
> Where it resolves to **more than one**, the route ends in
> `RouteOutcome.AMBIGUOUS`, nothing is performed, nothing is confirmed, and the
> outcome carries the candidates.

> **Normative.** No clause of this ADR permits choosing among candidates by rank,
> recency, score, best match, or a second model call. Ambiguity ends the route.

> **Normative.** The ambiguity listing is bounded by `DEFAULT_PAGE_SIZE` and is
> never truncated silently: a lookup that would exceed the bound is
> `RouteOutcome.AMBIGUOUS` over the bounded listing, and the reply composed for it
> says the request matched more than can be shown. No surface renders fewer
> candidates than the outcome carries or summarises in place of them (ADR-0186 §7's
> rule for a trail row, applied to a candidate listing).

**Ambiguity ends the route rather than parking on it, and this is a departure from
the shape the milestone's planning note sketched.** That note said ambiguity is "a
confirm that shows the candidates". It cannot be: `AssistantEngine.resume` takes
`approved: bool`, so a confirmation is a yes/no question and has no way to carry a
selection. The three ways to make it one are all worse than ending the route —
widening `resume` to carry a choice is a Protocol change on the busiest method of
the surface, for one caller; minting a second resume-like method is the same cost
with a second name; and confirming the *best* candidate is the guess the clause
above refuses. Ending the route costs the user one more sentence and costs this
decision nothing, and the candidates are on screen while they say it.

**The lookup reads the same store the operation reads, and that matters for
`forget`.** ADR-0073 §5 already names the window between showing a belief and
destroying it — "the show and the delete are two calls" — and rules that "the
consent an adapter collects is consent to forget **the belief that id names**, not
a guarantee that the bytes destroyed are the bytes rendered". A routed `forget`
inherits that window unchanged and does not widen it: the resolution, the render
and the delete are three points on the same path they already were, with a
confirmation between the second and the third.

### 6. Never re-read, stated as an invariant of the turn

> **Normative.** The result of a routed operation — the value the operation
> returned, the candidates a lookup produced, and the subject a confirmation
> showed — **never enters a model prompt**. Not in the pass that produced it, not
> in a later pass of the same conversation, and not through the conversation
> history a later turn retrieves.

> **Normative.** The composing stage is given, for a routed pass, exactly two
> values: the `RoutableOperation` that was routed to and the `RouteOutcome` it
> reached. Both are closed vocabularies this system owns. It is given no query, no
> resolved argument, no candidate, no record, no listing and no count.

> **Normative.** No adapter, setting, later ADR or implementing lane relaxes the two
> clauses above by rendering a routed result into text and supplying that text to a
> model. A lane that needs the model to see a routed result needs a different
> decision.

**The two clauses do different work and neither implies the other.** The first is
about the *data*: a read trail row carries a source name a stranger wrote, a
permission decision carries a tool description an MCP server supplied (ADR-0147),
and a belief carries whatever was ingested into it — so a routed result is exactly
the class of content ADR-0098 §2 exists for, and the cheapest conformance with §2
is not to render it. The second is about the *authority*: a model that can see what
`recent_decisions` returned is a model reading the control surface, and a system
that then let it route again would have built the chain §1 forbids structurally.
Forbidding both is what makes "one-directional" true rather than merely intended.

**What the user loses, and why it is not the answer they wanted anyway.** A reply
composed from an operation and an outcome cannot summarise the trail. It can say
*that* the assistant looked, and what it found in the coarsest terms the enum
carries. The listing itself is on screen beside it, rendered by the adapter from
typed values with the renderer that adapter already has for that operation — which
is ADR-0170 §6's shape exactly: the deterministic account is the assertion, and the
prose sits beside it. A user who asked "what have you read lately?" gets the read
trail, not a paraphrase of it, and the paraphrase is the part worth losing.

**And it is what keeps the answer honest under a hostile record.** ADR-0170 §6's
guarantee is that a model claiming an action the step account contradicts is
contradicted on the same screen. Here the guarantee is stronger, because the model
never saw the record at all: nothing in a source name or a tool description can
change what the listing beside the reply says.

### 7. The confirm rule: its own card, its own token, and none of ADR-0148's machinery

> **Normative.** A confirm-owed operation is never performed on the pass that routed
> to it. The pass **parks**: it returns `RouteOutcome.AWAITING_CONFIRMATION`
> carrying an `OperationConfirmation`, performs nothing, and composes no reply
> (§10). The operation runs only on a `resume` whose `approved` is `True`.

> **Normative.** A routed park is answered through `AssistantEngine.resume` with the
> `ContinuationToken` the confirmation carries, and through no other method. A
> `resume` whose `approved` is `False` performs nothing and returns
> `RouteOutcome.REFUSED`.

> **Normative.** `AssistantEngine.pending_confirmations` does **not** list a routed
> park, and a routed park is **not recovered across a restart**. A token presented
> to an engine that cannot resolve it yields `UnknownContinuationError` and never a
> denial, exactly as ADR-0084 §7 already requires of every unresolvable token.

> **Normative.** The confirmation card carries **no model-written text**. Its
> content is the `RoutableOperation` and the resolved subject as a typed value, and
> every word the user reads around them is the adapter's own, selected by the enum
> member. No free text the router produced — the query included — reaches the card.

> **Normative.** None of ADR-0148's per-call machinery applies to a routed
> operation, and no lane cites this ADR toward it. There is no `ActionRequest`, no
> `ToolDefinition`, no `ActionPolicy` ruling, no `PermissionDecision`, no
> `discloses` set, no canonical destination set, no payload description, no
> `EgressBinding`, and therefore no ADR-0181 §5 lineage gate and no ADR-0194
> ceiling. ADR-0021 §5's floor is not engaged, because nothing is being authorised
> to leave the device.

> **Normative.** ADR-0073 §5's show-then-confirm binds the routed `forget` whole,
> including its band-appropriate warning and its `--yes` idiom, which renders
> before acting rather than skipping the render.

**Why the card is not a `Confirmation`.** That type's four content members are
`tool_id`, `tool_description`, `parameters` and `reason`, and ADR-0177 §8 as
ADR-0178 §1 amended it obliges a surface to render all of them. A routed act has no
tool and no policy ruling, so three of the four would have to be filled with
something invented — the falsehood-in-durable-state failure ADR-0170 §3 refused,
reappearing in a value a user reads. `OperationConfirmation` is a second type
because the two carry genuinely different facts, not because a field was
inconvenient.

**Why a routed park is not recovered, stated as a cost rather than an omission.**
ADR-0052 §1 recovers a park by walking `plans.active_executions()` and reading the
pending `CONFIRM` out of the audit trail. A routed park has neither, so recovery
would mean a second durable park store built for this one shape. What a lost
routed park costs is one repeated sentence: **nothing has happened yet** — the
operation has not run, no side effect is pending, and the resolution is a lookup
the next ask redoes in the same way. An egress park is the opposite case and is
why ADR-0052 exists: there the user's approval is expensive to reconstruct and the
act may be irreversible. Trading a repeated sentence for a store is the right way
round, and the day a routed confirmation becomes expensive to reconstruct is the
revisit trigger rather than a defect found later.

**Why the direction of a write does not earn an exemption.** It is tempting to route
`revoke` freely — it only ever restricts, and restricting is the safe direction.
The reason it is confirm-owed anyway is that the router chose the *subject* as well
as the operation, and a `revoke` of the wrong source silently stops the assistant
reading something the user relies on. That failure is invisible until something
does not happen, which is the worst shape a failure can take in a system whose
whole product is that it noticed.

### 8. The contract surface

> **Normative.** `core/types.py` gains `RoutableOperation` (§3) and `RouteOutcome`, a
> `StrEnum` with exactly six members: `PERFORMED`, `AWAITING_CONFIRMATION`,
> `REFUSED`, `AMBIGUOUS`, `NOT_FOUND`, `FAILED`. `FAILED` means the operation
> raised, and the engine asserts nothing about whether it took effect.

> **Normative.** `core/types.py` gains `RoutedListing`, the type alias naming the
> arms a routed listing may take. Its arms are homogeneous tuples of types the
> promoted surface already carries: `tuple[Belief, ...]`, `tuple[Question, ...]`,
> `tuple[SourceReadRecord, ...]`, `tuple[RecordedInvocation, ...]`,
> `tuple[PermissionDecision, ...]`, `tuple[SourceGrant, ...]`,
> `tuple[SpendTotal, ...]`, `tuple[GrantableSource, ...]`. It mints no payload type
> of its own.

> **Normative.** `core/types.py` gains `OperationConfirmation`, frozen and
> `extra="forbid"`, with exactly three fields: `operation: RoutableOperation`, the
> resolved `subject: RoutedListing` holding exactly one element, and
> `token: ContinuationToken`.

> **Normative.** `core/types.py` gains `RoutedOperation`, frozen and
> `extra="forbid"`, with exactly four fields: `operation: RoutableOperation`;
> `outcome: RouteOutcome`; `listing: RoutedListing | None`, defaulting to `None`;
> and `confirmation: OperationConfirmation | None`, defaulting to `None`.

> **Normative.** `TurnOutcome` gains exactly one field: `routed`, typed
> `RoutedOperation | None` and defaulting to `None`. Its docstring names this ADR as
> the decision that added it, as `reply`'s names ADR-0170 §3.

> **Normative.** `RoutableOperation` — never pydantic's structural union resolution
> — is the discriminator that says which arm of `RoutedListing` a value is. A lane
> reads the arm off `operation`, and an implementation that infers it from the
> value's shape does not conform: an **empty** tuple is a legal value of every arm,
> so the shape decides nothing on exactly the case a listing is most likely to
> take.

> **Normative.** The implementing lane states these invariants as a
> `model_validator(mode="after")` on `RoutedOperation`, in **both** directions, as
> `StepOutcome._confirmation_matches_disposition` states its own: `confirmation` is
> present **iff** `outcome` is `AWAITING_CONFIRMATION`; `listing` is present **iff**
> `outcome` is `AMBIGUOUS` or `outcome` is `PERFORMED` on a read-only operation;
> and every element of `listing`, and of a confirmation's `subject`, is of the arm
> `operation` names.

> **Normative.** `TurnOutcome` gains a validator clause stating that `routed` and
> `step` are never both non-`None`. §1 ends the pipeline at a taken route, so a pass
> that routed drove no step, and an outcome carrying both would be describing two
> passes.

> **Normative.** On a pass that routed, `TurnOutcome.turn` is `None`, and this
> **partially supersedes ADR-0170 §4** in the scope the header names. `reply` is
> present, and `reply_degraded` may be `True`, beside a `None` `turn` **iff**
> `routed` is non-`None` and `routed.outcome` is not `AWAITING_CONFIRMATION`. On a
> routed park `reply` is `None` and `reply_degraded` is `False`. Every other clause
> of ADR-0170 §4, and ADR-0173 §6's widening, stand unchanged: an outcome carrying
> no `routed` obeys them exactly as before.

> **Normative.** The lane implementing this surface bumps `PROTOCOL_VERSION` in the
> **same change** and appends its reason to the running note in `wire/envelope.py`,
> as every bump since ADR-0131 §4 has. The number is deliberately not written here,
> since other lanes may move it first and a number in a ratified document cannot be
> corrected in place.

> **Normative.** Beyond the version constant and its note, no module under `wire/`
> changes for this surface. A result payload takes the shape of the method's own
> declared return annotation (ADR-0085 §10), so the field crosses the wire without a
> second declaration.

**The `turn is None` supersession is narrow and it is the same shape ADR-0173 §6
used.** ADR-0170 §4's reason for refusing a reply beside a `None` turn is stated in
its own text and in `TurnOutcome`'s validator message: "a recovered park persisted
no context and no memories, so there was nothing to compose from and any prose here
is about a turn this outcome cannot show". That reason is true of a recovered park
and false of a routed pass, where there **is** something to compose from — the
operation and its outcome — and the outcome shows it, in the `routed` member the
prose is about. So the clause is not relaxed; it is scoped to the shape its own
argument reaches, and every other shape refuses a reply exactly as before.

**Why `turn` is `None` rather than a `TurnResult` with a fabricated plan.**
`TurnResult`'s `plan` is required, and the only `ActionPlan` a routed pass could
supply is one nobody planned. ADR-0176 §6 made an *empty* plan a legitimate durable
record precisely because the planner asserted it; minting one here would persist a
planner's decision the planner never made, and `ActionPlan.rationale` — "why the
planner chose these steps" — would carry a sentence about a router. That is
ADR-0170 §3's refusal of `ActionPlan.rationale` as a home for an answer, arriving
one type further out.

**Why one field and not two.** A `routed: bool` beside a `RoutedOperation | None`
would be two answers to one question, which is ADR-0084 §3's argument against a
second length and ADR-0173 §2's against a sequence number. The presence of the
member is the fact.

**Why `RoutedListing` mints no type of its own.** Every arm is a type the promoted
surface already returns from the operation the arm belongs to, so a client
rendering a routed `recent_reads` uses the renderer it already has for
`recent_reads`. That is what keeps a widening under §3 cheap: a new read-only
member adds an enum member and, at most, one arm — not a wrapper model, a schema
and a renderer.

### 9. A routed operation is recorded, and the record is the routing decision

> **Normative.** Every routed operation that reaches a terminal `RouteOutcome` —
> `PERFORMED`, `REFUSED`, `AMBIGUOUS`, `NOT_FOUND` or `FAILED` — is recorded
> durably before the pass returns. A park is not a terminal outcome and is recorded
> when it resolves, under the outcome it resolves to.

> **Normative.** `core/types.py` gains `RoutedOperationRecord`, frozen and
> `extra="forbid"`: an `id`, the instant it was decided, the `RoutableOperation`,
> the `RouteOutcome`, whether a confirmation was owed and how it was answered, and
> the conversation the ask ran under. It carries **no content** — no query, no
> record contents, no listing, no free text — on ADR-0185 §2's ground, which is that
> a trail row is a statement about a decision and not a copy of what the decision
> was about.

> **Normative.** `core/protocols.py` gains `RoutingTrail`, the durable store, with
> four members on ADR-0185 §12's shape: `record`, `recent`, `export` and `clear`.
> It is a **new Protocol and owes the full triad** — Protocol, shared conformance
> suite, and canonical fake in `ai_assistant.testing` — in one change
> (`CONTRIBUTING.md` → "Adding a Protocol", ADR-0137 §3).

> **Normative.** The trail is bounded, on ADR-0185 §6's shape: a maximum row count
> read through `core.config.Settings`, pruned earliest-recorded-first, **with no
> spelling for "unlimited"**.

> **Normative.** `AssistantEngine` gains **no method** for this trail in this
> decision, and the trail is therefore unreachable from the CLI and from a browser.
> ADR-0177 §1's count of thirty does not move.

> **Normative.** The routing trail is a **fourth** row kind and joins neither of the
> two ADR-0186 §10 partitions: a routed operation is never a `PermissionDecision`
> and never a `SourceReadRecord`, and no lane widens `recent_decisions`,
> `export_decisions`, `recent_reads` or `export_reads` to return one.

**Recording it is the delegated call, and this is why it went that way.** Every
other place a model's choice reaches an effect in this system leaves a durable
record: a plan's steps become `StepExecution` rows, a permission ruling becomes a
`PermissionDecision`, a source read becomes a `SourceReadRecord`, an authorised
call becomes a `ToolInvocation` (ADR-0192), a memory write becomes a
`MemoryDecision`. A routed `forget` would be the sole exception — and it is the one
that destroys the only evidence of itself, since `AssistantEngine.forget` "relays
`MemoryStore.delete` and nothing more". Leaving the new door unrecorded because the
old door is would be reasoning from the gap rather than from the rule.

**The asymmetry objection is real and it is answered by scope rather than
dismissed.** A `forget` through the typed door records nothing today; after this,
the same act through the routed door records a row. That is not incoherent, it is
incomplete: the fact worth recording about a routed act is that a **model** chose
it, which the typed door has no equivalent of. Whether the typed door should
record its own deletions is `track:memory` ground — ADR-0073's contract and
ADR-0007's deletion right — and §11 files it rather than deciding it here.

**No read surface is minted, and that is ADR-0185 → ADR-0186's own sequence.**
ADR-0185 §12 minted `SourceReadTrail` with `recent` and `export` and gave the user
nothing to read them with; ADR-0186 §1 gave the two engine operations later, and
argued the bound, the ceiling and what a row renders as on their own merits. Doing
the same here keeps this decision to routing and leaves the surface to a decision
that can weigh it — including whether the four trails should be read through four
pairs of methods or something better, which is a question this ADR would answer
badly by answering it incidentally.

**`clear` is on the Protocol because ADR-0007's deletion right does not have an
exception for trails**, and a row naming a conversation the user deleted is a
pointer into nothing. The trail store's own lifecycle is the implementing lane's,
under the settings shape above.

### 10. Rendering, composition and failure

> **Normative.** An adapter renders the routed account — the operation, the outcome,
> and the listing where one is carried — **in addition to** any composed reply,
> never instead of it, and never in place of it. Where the two disagree the routed
> account is correct by construction, and no adapter, setting or later ADR resolves
> that disagreement in the reply's favour or suppresses the account to remove it.
> This is ADR-0170 §6's rule, and it binds here for ADR-0170 §6's reason.

> **Normative.** On a routed pass that is not a park, the composing stage runs on
> §6's two inputs and an answer is owed. A composition failure degrades the pass
> exactly as ADR-0170 §8 rules — `reply` `None`, `reply_degraded` `True`, the
> outcome returned rather than raised — and the routed operation's own outcome is
> unaffected by it. An operation that ran is still reported as having run.

> **Normative.** On a routed park the composing stage is not reached, originates no
> model call, and `reply_degraded` stays `False` — ADR-0170 §4's rule for a parked
> step, for its own reason: the confirmation is what the user must answer, and
> prose beside it competes with the question.

> **Normative.** `converse_streaming` routes identically to `converse`. A routed
> reply streams as any other reply does (ADR-0173), and `routed` rides the terminal
> `TurnOutcome`.

> **Normative.** The exchange of a routed pass is **captured** (ADR-0074 §3), and
> the captured content carries the user's utterance. A routed pass produces no
> `TurnResult`, so the implementing lane threads the utterance to the capture point
> rather than reading it off a turn that is not there. Whether the routed operation
> itself joins the captured episode is #1314's ground and is not decided here.

> **Normative.** A routed listing is bounded by the existing result-payload ceiling
> and gets no setting of its own. `check_payload` already refuses an oversized
> result symmetrically at both ends (ADR-0085 §8, §8c), and a listing that would
> breach it is that refusal — never a silent truncation.

> **Normative.** Every string an adapter renders out of a routed account is
> neutralised before display exactly as it neutralises the confirmation content,
> the plan's rationale and a policy's reason (ADR-0042 §4). On the CLI that is
> `interfaces.cli._safe`.

**The account is the guarantee and the reply is not, and here the split is sharper
than ADR-0170 §6's.** There the prose could contradict the step account because the
model had seen the account. Here it has seen two enum values, so the worst it can
produce is prose about the wrong thing — and the listing beside it is typed data
from the store, which no prompt influenced. The composed reply on a routed pass is
close to ceremony, and it is kept because a person who asked a question in words is
owed an answer in words, and because a pass that answered with a bare table would
read as a different product.

**The capture clause is the one obligation a lane will discover the hard way.**
`Engine._capture` builds its episode content from the turn, and a routed pass has
none — so a lane that wires routing without threading the utterance produces a
captured exchange with the user's own sentence missing from it. That would be a
silent hole in the conversation record, visible only to the next person to resume
that conversation.

### 11. What this ADR does not decide

> **Normative.** Beyond §§1–10 and §13, this ADR decides nothing. It registers no
> tool, designates no seam, changes no method signature on `AssistantEngine`, and
> adds no `core` name other than §8's five and §9's two. A lane needing any of those
> needs its own change and, where golden rule 5 reaches it, its own ADR.

- **Milestone 27 — multi-step plan driving** (#242). ADR-0170 §5's "at most a
  plan's first step is driven" is untouched. A routed ask drives no plan step at
  all, so this decision neither depends on that limit nor relaxes it.
- **A read surface for the routing trail.** §9 mints the store and no engine
  method. The surface is its own decision, on ADR-0185 → ADR-0186's sequence, and
  should weigh whether four trails want four pairs of operations.
- **Whether a `forget` through the typed door is recorded.** `track:memory`
  ground — ADR-0073's contract and ADR-0007's deletion right — and the asymmetry
  §9 names is filed rather than closed here.
- **Whether the routed operation joins the captured episode** (#1314), which
  ADR-0170 §9 already left to `track:memory` for the composed reply, on the same
  ground.
- **Recovering a routed park across a restart.** §7 rules it out with its cost
  stated; the revisit trigger is a routed confirmation that becomes expensive to
  reconstruct, not the passage of time.
- **Selecting among ambiguous candidates in one exchange.** §5 ends the route;
  widening `resume` to carry a selection is a Protocol change for one caller and is
  not made here.
- **The engagement surface**, which #1312 carries as deferred and which this
  decision does not touch.
- **Voice's spoken route** (#1318). A spoken ask reaches `converse` like any other
  and routes by these rules; whether speaking changes what may be confirmed by
  voice alone is `track:voice`'s.
- **`beliefs`, `learn`, and the twenty-eight operations §3 leaves out.** The
  widening rule is how they arrive, and each arrival owes §3's five conditions
  stated in its own lane's ADR.
- **The router's prompt text and which model answers.** `orchestration`'s to write,
  under §4's constraints on what it contains.

### 12. What the implementing lanes owe

This decision is larger than one lane. ADR-0137 §2 makes the contract triad and its
primary production implementation one unit of work, and ADR-0173's implementation
across three PRs is the precedent for an ADR that lands in more than one.

> **Normative.** §9's `RoutingTrail` triad — Protocol, shared conformance suite,
> canonical fake — lands with its primary production implementation in one change
> (ADR-0137 §2, §3). It is not split, and it is not deferred behind the router.

> **Normative.** §8's `core` surface lands with the routing stage and the engine
> wiring that consumes it, in one change, with §8's `PROTOCOL_VERSION` bump in the
> same change.

> **Normative.** The lane landing §8 ships tests pinning: `RoutedOperation`'s
> validator in **both** directions on each of the three invariants; the
> `routed`/`step` mutual exclusion; and §8's widened `TurnOutcome` shape — a routed
> non-park carrying a reply beside a `None` turn, a routed park carrying neither,
> and a **recovered** park still refusing a reply, so the supersession is pinned as
> narrow rather than as a relaxation.

> **Normative.** The same lane ships §4's decline tests on ADR-0176 §1's own model:
> a parameterized test that `1`, `1.0`, `"true"`, `"yes"` and JSON `false` are each
> **not** the `no_operation` marker and the JSON boolean `true` is; and a test that
> an `operation` value which is not a `RoutableOperation` member declines rather
> than resolving onto a near match.

> **Normative.** The same lane ships a test that a routing prompt assembled for an
> utterance is **byte-identical** whether the store holds a hostile record or none,
> pinning §4's last clause structurally rather than by inspection.

> **Normative.** The same lane ships §6's tests under a **deliberately contradictory
> provider**: a fake composer asserting it was handed only a `RoutableOperation` and
> a `RouteOutcome`, over a routed `recent_reads` whose listing contains a record
> whose fields carry the composer's own container syntax, asserting that no part of
> the listing appears in the assembled prompt. A test asserting only that the
> composer was called does not satisfy this clause.

> **Normative.** The same lane ships §5's three resolution cases — none, one, more
> than one — asserting that the many-candidate case performs **nothing**, and §7's
> park-and-resume pair asserting that a refused resume performs nothing and that a
> routed park does not appear in `pending_confirmations`.

> **Normative.** The same lane ships §9's recording tests: a row for each terminal
> outcome, no row for a park until it resolves, and a row carrying no query and no
> record contents.

> **Normative.** A separate lane may land the CLI and gateway renderings of §10.
> They are a **consumer group**, not a second decision: each renders the routed
> account beside the reply with the renderer it already has for the operation, and
> neither derives, defaults or composes an argument (ADR-0177 §1's fourth clause,
> which the gateway continues to obey because it makes no routing decision — the
> hub does).

The contradictory-provider test is the one that matters most and the easiest to
omit, because every natural test of a composing stage uses a fake that cooperates.
A cooperating fake cannot distinguish a design whose never-re-read property is
structural from one whose property is a hope about how the stage was wired.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a
reader holding only that ADR now act differently, or read one of its clauses more
widely than it now holds?

**ADR-0170 §4 — a record is owed, and it is a partial supersession.** That section
rules `reply` `None` on "exactly three shapes", names the second as "a pass whose
`turn` is `None`", and rules `reply_degraded` "never `True` … where `turn` is
`None`". §8 above admits a fourth shape in which `turn` is `None`, `reply` is
present and `reply_degraded` may be `True`. A reader holding only ADR-0170 would
build a validator that refuses the routed outcome, so this is a change to what was
decided and not a reconciliation of it. It is **partial**, and deliberately narrow:
the park shape, the recovered-resume shape, the composition-failure shape, the
`reply_degraded` flag's meaning, and ADR-0173 §6's widening are untouched, and an
outcome carrying no `routed` is ruled exactly as ADR-0170 ruled it.

**ADR-0052 §1 — a record is owed, and it is an amendment.** That section's
algorithm reconstructs parked confirmations from `plans.active_executions()` and
the audit trail, and describes its product as "the confirmations a user may still
answer". §7 above creates a park that algorithm cannot reach, so the sentence now
reads more widely than it holds — ADR-0082 §1's second limb. Nothing it decided
changes: a reader implementing §1's four steps writes identical code before and
after, and every confirmation §1 ranges over is still recovered. So it is an
amendment, recorded as an appended dated note and a qualifier on the `Status` line
— except that ADR-0052's `Status` is led by `Partially superseded by`, so ADR-0082
§2 puts the record in the note alone.

**Everything else is a stacked addition and no record is owed.** ADR-0170 §§1, 5,
6 and 8 (the pipeline gains a second stage without any clause of ADR-0170's
becoming false; §6's rendering rule is cited and obeyed, not narrowed; §8's
degradation rule is applied to a new pass rather than changed). ADR-0173 (§6's
fourth shape stands whole; §10 above adds a fifth in a member ADR-0173 does not
mention). ADR-0176 (a routed ask never reaches the planner, and §4's test between
the two envelope shapes is unchanged for every ask that does; §1's marker
strictness is *followed* here, not modified). ADR-0177 §1 (its enumeration of
thirty is unchanged, its third clause's count is unchanged because §9 adds no
`AssistantEngine` method, and its fourth clause is obeyed by §12's consumer group).
ADR-0148, ADR-0021 §5, ADR-0154 and ADR-0017 §3 (§7 asserts that none of them is
engaged, which is a claim about routing and not about them). ADR-0186 §10 (its
partition is a rule about the relation between two named trails and is restated,
not widened, by §9's fourth row kind; ADR-0192 already added a third without
disturbing it). ADR-0185 §§2, 6 and 12 (§9 follows their shapes; it changes none of
their clauses). ADR-0073 §5 (§7 binds it whole). ADR-0084 §8 (§8's `RouteOutcome`
is argued against it below rather than changing it). ADR-0085 §4 (its Group A table
will read short against the tree, exactly as its Group F `Disposition` row has since
ADR-0145 §4; ADR-0170 §3 settled that practice for `TurnOutcome` itself and this
decision follows it rather than opening a third way). ADR-0098 §2 (§4 satisfies it
structurally by assembling no external content; the clause is not narrowed).
ADR-0082 §1 is explicit that a record demanded on book-keeping grounds alone is not
owed, and none is taken.

**ADR-0084 §8 is the one worth arguing rather than listing.** That section refused a
`FAILED` member on `Disposition` because it would "fuse two independent axes (did
the gate let it run / did the run succeed) into one enum", and `RouteOutcome`
carries `AWAITING_CONFIRMATION` and `REFUSED` beside `PERFORMED` and `FAILED`,
which looks like the fusion it refused. The reason it is not is the reason ADR-0084
§8 gave: `Disposition` could stay a gate verdict because `StepOutcome.state`
already carried the step's own status, so a client had a second value to read. A
routed operation has no `ExecutionState` and no durable step, so splitting the enum
would mint a second value whose only job is to be read beside the first, and whose
disagreement with it would have no defensible interpretation. One enum with a
closed set and a two-directional validator is the shape that keeps
`RoutedOperation` unable to describe a pass that did not happen.

**This ADR supersedes nothing wholly and withdraws nothing.**

**The two records are stated here in their exact form and are not made by this
change** (ADR-0026 §6, ADR-0030 §6, ADR-0032 §8): writing "amended by ADR-0197"
onto a ratified ADR while ADR-0197 is only `Proposed` is the state claim ADR-0019
forbids. The lane that ratifies this ADR makes them, and no other lane does.

- **ADR-0170.** Its `Status` line, which today reads `Partially superseded by
  ADR-0173 (…)`, gains this ADR's pair on the same line without dropping ADR-0173's
  (ADR-0070 §4): `and ADR-0197 (§4's second None shape and its two clauses stated
  in the "turn is None" direction, each only as it reaches an outcome carrying
  TurnOutcome.routed)`. It gains an appended dated header note recording the
  supersession's scope and its ground, ending `Refs #1623, ADR-0197 §8, §13`.
- **ADR-0052.** Its `Status` line is led by `Partially superseded by ADR-0084 (…)`,
  so no qualifier is written on it (ADR-0082 §2). It gains an appended note:
  `Amended: <ratification date> by ADR-0197 — §1's "the confirmations a user may
  still answer" is true of every confirmation §1's algorithm ranges over and does
  not reach ADR-0197 §7's routed park, which holds no execution, no step and no
  recorded CONFIRM for §1's four steps to recover. Nothing §1 decided changes.
  Refs #1623, ADR-0197 §7, §13.`

## Consequences

- **The assistant can act on itself when asked in words.** "Forget that I like
  jazz" shows the belief, takes a yes, and destroys it. "What have you read
  lately?" answers from the read trail. VISION's *In Control* verbs stop being
  buttons only.
- **Every ask that is not routed costs one more model call.** Three where there
  were two. That is the price of the door and it is paid on the common case; §1
  states it, and the revisit trigger is a measured latency or cost regression on
  ordinary turns rather than a hunch about one.
- **A routed ask is cheaper than an ordinary one, which is the direction nobody
  expects.** It skips context assembly, memory retrieval and the planner's model
  call. The router's call and the composer's are the whole of it.
- **`TurnOutcome` carries a seventh field and clients gain a branch.** A client that
  ignores `routed` renders a turn that did something as a turn that did nothing —
  which is why §10's rendering clause is normative and why the CLI and gateway are
  named as owing the rendering rather than left to notice.
- **The model can now select a destructive operation, and the confirmation is the
  whole of what stands between it and the act.** That is a real widening of what a
  wrong model output can reach, stated rather than minimised. What bounds it: the
  vocabulary is closed and enumerated, the subject is a lookup and never a
  generation, ambiguity ends the route, and the card renders the resolved subject
  before the user answers.
- **A fourth trail exists and nothing can read it yet.** §9 records the routing
  decision and mints no engine method for it, so the row is written for a surface a
  later decision gives it. That is ADR-0185's own position for a day, and it is a
  cost: an operator debugging a routed act reads the store directly until then.
- **The routing trail does not answer the deletion question it makes visible.** A
  `forget` through the typed door still records nothing, and the two doors now
  differ. §11 files it as `track:memory` ground.
- **A routed park does not survive a restart.** The user repeats one sentence. The
  alternative was a second durable park store, and §7 states the trade rather than
  hiding it.
- **Revisit if** a routed confirmation becomes expensive for a user to reconstruct,
  which is when §7's recovery trade flips; if the vocabulary's widening rule is
  exercised often enough that a lane wants a generic argument resolver rather than
  a per-operation lookup; or if a consumer appears that genuinely needs the model
  to see a routed result, which is when §6 is the clause to amend and not to work
  around.

## Alternatives considered

**Fold the router into the planner's envelope as a third shape.** ADR-0176 already
gave `ModelBackedPlanner` two envelope shapes and a marker discriminating them; a
third — `{"operation": …, "query": …}` — would cost **zero** extra model calls,
which is this decision's largest cost. *Rejected* on placement, for two reasons.
`planning/`'s product is an `ActionPlan` and a routed operation is not one, which
is ADR-0170 §2's argument for keeping the composing stage out of `planning/`
applied to the same seam. And the routable vocabulary is `AssistantEngine`'s own
façade, so a planner that knew it would be one subsystem reaching for another's
surface — the coupling golden rule 1 forbids and which ADR-0047 §5 already declines
in the smaller case of a tool registry. There is a third, narrower reason: ADR-0047
§6's bounded repair would then give a model a second chance to change the *route*,
so a repair round taken for a malformed step could return a `forget`.

**Register the hub's operations as tools.** Give `ToolRegistry` a `forget` tool and
let the planner select it like any other. *Rejected.* It routes a local operation
through ADR-0148's per-call machinery and ADR-0021 §5's floor, demanding a
canonical destination set and a payload description for a call with no recipient;
it obliges an ADR-0016 declaration with a `discloses` set for a call that discloses
nothing to anyone; and it writes a `StepExecution` naming a tool and an approval for
an act that is not an egress. It is ADR-0170 §1's refusal, from the other side.

**Let the composing stage read the routed result and answer from it.** One model
call fewer than a listing plus prose, a much better sentence, and the shape every
commercial assistant has. *Rejected* in §6, and it is the alternative with the most
to recommend it. What it costs is the one-directional property: the model would be
reading the user's beliefs, permission decisions and read trail — content ADR-0098
§2 exists for — and a system that showed a model the control surface would then
have to argue, every time, why it may not act on what it saw. The listing beside
the reply is a worse sentence and a better system.

**Carry the routed result as `FrozenJson`.** One field, no union, and a widening
that adds nothing to `core` at all. *Rejected.* It discards the typing ADR-0085
built the promoted surface on: every client would re-derive the shape of a
`SourceReadRecord` from an untyped mapping, and the renderer it already has for
that type would not accept the value. `RoutedListing`'s arms are the types the
surface already declares, which is what makes the client side of §12 an adaptation
rather than new machinery.

**Give `RoutedListing` a wrapper model per operation, discriminated by a `kind`
member.** The pydantic-native way to write a tagged union, and it removes §8's
empty-tuple ambiguity at the type level. *Rejected* on cost: eight wrapper models
now and one per widening later, each with a schema, a docstring and a test, to
carry a discriminator that `RoutedOperation.operation` already carries. §8's clause
names the discriminator instead, and the ambiguity it names is real only for a
reader who ignores that clause.

**Route without a confirmation for the "safe" direction.** Let `revoke` and
`forget_question` run straight through, since one restricts and the other discards
something the assistant asked for rather than something the user said. *Rejected*
in §7. The router chose the subject as well as the operation, and a `revoke` of the
wrong source is invisible until something the user relied on stops happening.

**Defer the record.** Ship routing now and decide the trail with the milestone's
own QA evidence. *Rejected* in §9. The first thing the evidence would show is a
`forget` nobody can account for, and a decision that has to be retrofitted onto
rows that were never written cannot recover the ones that were not.

**Leave it deferred.** The status quo, stated as a choice: `ask` keeps reaching the
world and not the hub, and the control surface stays typed. *Rejected.* It is the
track's remaining named content, it is the half of *In Control* a person cannot
reach by talking, and the reason it was deferred — that a reply had to exist first —
was discharged by ADR-0170.
