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
  this PR is. The surface is one field on `TurnOutcome` and five new
  `core/types.py` names (§8), plus two more `core/types.py` names, two new
  Protocols in `core/protocols.py` and one error class (§9). The implementation is separate
  lanes against this ADR once it is merged (golden rule 5, ADR-0015 §5).
- **It partially supersedes ADR-0170 §4** — that section's second `None` shape and
  its two clauses stated in the `turn is None` direction, exactly as far as they
  reach an outcome carrying §8's `routed` member, and no further. §13 states the
  record and the reasoning; §8 states the replacement invariants.
- **It amends ADR-0052 §1** by a reading and not by a decision: that section's
  "the confirmations a user may still answer" is true of every confirmation it
  ranges over and is not true of §7's routed park, which holds no plan state for
  §1's algorithm to recover. §13 states the record.
- **It partially supersedes ADR-0052 §3 and ADR-0042 §4**, in one scope each and
  no further: `resume`'s ratified "the step … is always present", and ADR-0042
  §4's guarantee that `approved=False` becomes a `DENY` ruling, each only as it
  reaches a `resume` answering §7's routed park. `AssistantEngine` gains no
  method, but one method's **contract** moves, and that is what these two records
  are for. §7 states the routed resume's replacement invariants, §12 the
  conformance coverage that pins them as narrow, and §13 the records.
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

The gap is not that the operations are missing. `forget`, `revoke`,
`recent_reads`, `spend_totals` and the rest are all on the promoted surface, all
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

**Its own confirm rule.** `forget` destroys, and `revoke` and `forget_question`
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
> persisted, no step is driven and no `ToolRegistry`, `ActionPolicy` or
> `ToolInvoker` is reached. A routed pass that **parks** takes a slot at the
> engine's outstanding-confirmation ceiling, which §7 states; a routed pass that
> does not park takes none. The composing stage still runs, on
> §6's inputs.

> **Normative.** The routing stage is entered on a `converse` or
> `converse_streaming` pass and on **no other**. `AssistantEngine.resume` routes
> nothing: it carries an opaque `ContinuationToken` and a boolean and no utterance,
> so there is no input a router could consume, and what it performs is the
> operation an earlier pass already routed to. It is nevertheless part of that
> route's lifecycle: §9's second row is written on it, under the `route_id` the
> parked entry carries.

> **Normative.** **One ask performs at most one routed operation, by
> construction.** The routing stage runs once per pass that enters it, and no
> clause of this ADR, and no later ADR citing it, permits a routed operation's
> result to select a second operation — within that pass, or on the `resume` that
> resolves its park.

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
> Protocol"). §9's two trail Protocols are a separate surface and owe their own
> triads; the stage holds the write-only half of that pair and nothing more.

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

### 3. The routable vocabulary: nine operations, each tagged, and the rule that widens it

> **Normative.** `core/types.py` gains `RoutableOperation`, a `StrEnum` whose members
> are the operations an ask may be routed to. Its members are exactly these nine,
> named for the `AssistantEngine` operation each routes to:
>
> - **read-only** — `questions`, `recent_reads`, `recent_invocations`,
>   `recent_decisions`, `standing_grants`, `spend_totals`;
> - **confirm-owed** — `forget`, `revoke`, `forget_question`.

> **Normative.** Every member above takes **exactly one** argument that varies with
> the ask, or none: a confirm-owed member takes the one identity §5's lookup
> resolves, and a read-only member takes none and is called with the promoted
> surface's own declared defaults. An operation taking a second varying argument —
> a scope, a mode, an accept/reject decision, a preferences object — is outside the
> vocabulary until a decision says how that argument is chosen, rendered and
> confirmed.

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

> **Normative.** **The widening rule.** A member added to `RoutableOperation` is a
> `core/types.py` change and is therefore ratified contract-first like any other
> (golden rule 5, ADR-0015 §5). What this rule fixes is the **test** such a change
> must meet, and that meeting it needs no *further decision about routing*: the
> widening rides the contract ADR its own lane already owes, in the practice
> `Disposition` already follows — `INVALID_PARAMETERS` by ADR-0145 §4 and
> `EGRESS_UNBINDABLE` by ADR-0152 §9, each on the authority of the ADR that decided
> the member. A member may be added exactly when the operation satisfies all five
> of: (i) it is a member of the promoted `AssistantEngine`
> surface; (ii) performing it reaches no egress boundary — no `ToolRegistry`, no
> `ToolInvoker`, no `EgressDestination`, no credential; (iii) its arguments are
> either none, or resolvable by §5's deterministic lookup from a router-named
> query; (iv) it is tagged by the test above; and (v) where it is read-only, its
> result type is already an arm of §8's `RoutedListing`. An operation failing any of
> the five is outside the vocabulary until an ADR puts it inside.

> **Normative.** A lane exercising the widening rule states, in that ADR, which of
> the five conditions each added member satisfies and how. Adding a member silently
> does not satisfy this clause, and neither does citing this ADR in place of the
> statement.

**Why a starter set rather than every non-egress operation.** Most of the
thirty-nine pass conditions (i) and (ii). What stops them is (iii) and (v):
`grant` takes a `Sequence[GrantScope]` beside its source and `answer` takes an
`accept: bool` beside its question, neither of which any query resolves to;
`set_notification_preferences` takes a whole `NotificationPreferences` object;
`belief` and `conversation` take an id a user does not say; `observe` returns an
`ObservationReport` no arm carries. The nine above are the ones a person says out loud whose whole argument
is one identity, and the vocabulary is closed at what has been argued rather than
at what would compile.

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
memory through `answer` on an open question, and `answer` is itself outside this
vocabulary for the reason §11 gives — it takes an `accept: bool` beside the
question's identity, and a router that supplied it would be deciding the
correction rather than routing to it. ADR-0177 §1's third clause already holds
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
> argument. It is performed **exactly as the promoted surface declares it**, with
> that surface's own defaults and that surface's own bound, and routing changes
> neither. For the paged members — `questions`, `recent_reads`,
> `recent_invocations`, `recent_decisions` — that bound is the surface's own
> `DEFAULT_PAGE_SIZE` default, and routing gets no setting of its own, for ADR-0170
> §8's reason applied here: an existing ceiling that already bounds this listing
> everywhere else is the ceiling. `standing_grants` and `spend_totals` are **not
> paged**, take no `limit` and no `offset`, and a routed call to either inherits its
> declared behaviour whole — including `standing_grants`' "complete or refused,
> never truncated" (ADR-0139 §2), whose `OversizedValueError` reaches a routed pass
> as `RouteOutcome.FAILED` like any other raise. No clause of this ADR imposes a
> page on a member the promoted surface declares unpaged, and none may: doing so
> would make a routed answer differ from the same operation's typed-door answer,
> which is the one thing §2's third clause exists to prevent.

> **Normative.** The lookup's candidates are **typed records**, and the operation's
> argument is a **scalar identity read off one of them** by a fixed per-operation
> mapping — not the record itself, which no confirm-owed member's signature
> accepts. The mapping is total over §3's confirm-owed members and is exactly:
> `forget` takes `Belief.id`; `forget_question` takes `Question.id`; `revoke` takes
> `SourceGrant.source`. A member added under §3's widening rule states its own
> mapping in the ADR that adds it, and condition (iii) is not satisfied without one.

> **Normative.** The two are carried separately and neither substitutes for the
> other. The **display subject** is the typed record, and it is what §7's card
> renders and what an `AMBIGUOUS` listing carries, because a person judges the
> belief and not its id. The **scalar argument** is what §2's façade call is made
> with, and it is what the park retains and §9's row records as `subject`.

> **Normative.** Where the lookup resolves to **exactly one** candidate, that
> candidate is the display subject and the identity read off it by the mapping
> above is the argument. Where it resolves to **none**, the route
> ends in `RouteOutcome.NOT_FOUND`, nothing is performed and nothing is confirmed.
> Where it resolves to **more than one**, the route ends in
> `RouteOutcome.AMBIGUOUS`, nothing is performed, nothing is confirmed, and the
> outcome carries the candidates.

> **Normative.** No clause of this ADR permits choosing among candidates by rank,
> recency, score, best match, or a second model call. Ambiguity ends the route.

> **Normative.** The ambiguity listing is bounded by `DEFAULT_PAGE_SIZE` and is
> never truncated silently, and the disclosure rides the **outcome** rather than a
> count. A lookup resolving to more than one candidate but no more than the bound
> ends in `RouteOutcome.AMBIGUOUS`; a lookup that would **exceed** the bound ends
> in `RouteOutcome.AMBIGUOUS_TRUNCATED` over the bounded listing, and that member
> is the whole of what tells the reply the request matched more than can be shown.
> The two are otherwise identical: both perform nothing, both confirm nothing, both
> carry the listing, and both write no row (§9). No surface renders fewer
> candidates than the outcome carries or summarises in place of them (ADR-0186 §7's
> rule for a trail row, applied to a candidate listing).

**The eighth member exists because §6 leaves no other channel, and that is the
right way round.** §6 gives the composing stage exactly two closed values and
explicitly no count — so a single `AMBIGUOUS` cannot distinguish two candidates
from a hundred, and a reply that disclosed truncation for every ambiguity would be
false on the two-candidate case while one that never disclosed it would be false on
the overflow case. The alternative is handing the composer a number, which is a
count of the user's own records reaching a prompt and the first crack in §6's
second clause. A closed enum member carries the same one bit and carries nothing
else, which is what §6 is for.

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

> **Normative.** A `resume` that answers a routed park differs from a `resume` that
> continues a parked step in exactly **three** respects and in no others. Its
> `TurnOutcome` carries `step` `None` and `routed` non-`None`, which is §8's mutual
> exclusion read from the resume end. Its refusal is **returned, never raised**:
> `approved` `False` yields `RouteOutcome.REFUSED` on that member and **no**
> `PermissionDeniedError`, because no `ActionPolicy` is consulted and no
> `PermissionDecision` is recorded, so there is no ruling for a refusal to be — and
> a refusal is a `REFUSED` row (§9) rather than an exception. And its `turn` is
> `None` for §8's reason rather than ADR-0052 §3's. Everything else is unchanged:
> `UnknownContinuationError` on a token this engine cannot resolve — unknown,
> expired, already claimed, or from a previous process life (ADR-0084 §7) — the
> `timeout` argument's meaning, and the whole of a `resume` answering an ordinary
> parked step, which continues to carry its step and to raise
> `PermissionDeniedError` on a refusal exactly as it does today.

> **Normative.** A routed park holds a slot at the engine's existing
> **outstanding-confirmation ceiling** — `max_outstanding_confirmations`, the bound
> that exists because "a client that requests confirmable actions and abandons every
> token would grow the table without bound". A routed park is exactly that shape and
> takes no exemption from it: the slot is reserved before the park is registered and
> a route that cannot reserve one meets the same backpressure the engine already
> applies at that ceiling, in the same form. The ceiling gets no second setting and
> no routed-only variant.

> **Normative.** A reservation that does not become a registered park is **released
> on every path**, without exception: the row of §9 failing to write, the id factory
> raising, the resolution raising, the pass being cancelled at any await between the
> reservation and the registration, and any defect in the code between them. The
> reservation is held across those awaits and released in a `finally`, which is what
> `Engine._converse` already does with the handle it reserves before driving a step
> — `self._reserved.discard(handle)` in a `finally`, so the slot is freed whether the
> step parked or did not. A slot that can be reserved and never released is the
> memory-exhaustion vector the ceiling exists to close, reintroduced through the
> ceiling itself: repeated trail failures would otherwise reserve up to the ceiling
> and block every later confirmation with no park to evict.

> **Normative.** A routed park has a **bounded lifetime**. It is evicted once that
> lifetime has elapsed since it was registered, releasing its ceiling slot, and its
> token thereafter resolves nothing and raises `UnknownContinuationError` like any
> other unresolvable token (ADR-0084 §7). Elapse is measured against the **injected
> clock** (ADR-0009), never a wall clock read at the seam, so a test advances it
> rather than waits.

> **Normative.** `core.config.Settings` gains `routed_confirmation_ttl`, a
> `_DurationSetting` — deliberately **not** `_NullableDuration` — defaulting to
> `timedelta(minutes=15)` and validated at load as strictly positive. `None` is not
> a value it accepts: it takes no part in the disable sentinel `confirmation_ttl`
> opts into, which is exactly the wrong default to inherit here, and a zero or
> negative duration is refused at load rather than producing a card unusable the
> instant it is rendered. It is the whole of this decision's lifetime configuration,
> and no second setting scales, extends or disables it.

> **Normative.** Expiry is checked **inside the claim**, under the same lock and
> before the token resolves anything. A `resume` presenting a token whose park has
> elapsed raises `UnknownContinuationError`, evicts the entry and releases its slot,
> whether or not any capacity has been sought and whether or not
> `pending_confirmations` has run since. Eviction elsewhere — when a slot is sought,
> and in `pending_confirmations`' existing reconciliation — is opportunistic
> housekeeping that reclaims slots earlier; it is never what makes an expired park
> unusable. This decision adds no scheduler and no background job.

> **Normative.** A `resume` whose row cannot be written ends in
> `RouteOutcome.UNRECORDED` with the park **already claimed** — §9 orders the write
> before the effect and the claim before the write — so the token is spent, the
> slot released, and nothing performed. The remedy is this section's own sentence:
> nothing has happened yet, and the operation is asked for again rather than
> resumed again. A surface that told the user to retry the token would be telling
> them to present one that now raises `UnknownContinuationError`.

> **Normative.** An evicted park writes **no** row. §9's `OWED` row already stands
> and its meaning is unchanged: a route was decided and no answer came. The absence
> of a second row is what an unanswered park looks like, whether the user walked
> away or the park expired, and no reader distinguishes the two from the trail.

> **Normative.** A routed park is **claimed once, atomically**, under the same lock
> the engine's existing park resolution runs under, and the claim is what evicts it:
> the entry is removed before the row of §9 is written, before the operation is
> called, and before anything is composed. A second `resume` presenting the same
> token — concurrent or later, and whatever its `approved` value — resolves nothing
> and raises `UnknownContinuationError`, so one park yields one answer, one row pair
> and at most one operation, which is what §1's one-operation clause costs at this
> seam.

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

**Two sentences of the ratified `resume` contract move, and §13 records both.**
`core/protocols.py`'s `AssistantEngine.resume` docstring states "The step is what a
resume is for and is always present" — ADR-0052 §3's sentence, carried onto the
surface ADR-0084 §5 promoted — and declares `PermissionDeniedError: If the human
refused`, whose guarantee is ADR-0042 §4's "only `approved=False → DENY` is
guaranteed". A routed resume has no step and produces no ruling, so both read more
widely than they hold the moment `routed` is present. A method's *contract* moving
is a change to a promoted surface whether or not the surface gains a method, and
this one gains none: §13 classifies the two as two partial supersessions, scoped to
exactly those two sentences and exactly that case, rather than leaving them as an
implementation detail of this decision.

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
the next ask redoes in the same way.

**The lifetime is what makes that sentence true rather than aspirational, and it is
there because the park is deliberately invisible.** A tool park has two ways back —
`pending_confirmations` enumerates it, and its durable binding survives a restart —
so a token lost in flight is recoverable by asking. A routed park has neither by
design, so without a lifetime a client that disconnected between the park and its
token would hold a slot nothing could ever free: at a ceiling of one, the very next
"forget that I …" would meet backpressure rather than a fresh card, and repeating
the sentence would be exactly what does not work. Bounding the lifetime is the
cheapest way to keep the invisibility from becoming a leak, and it is why the
enumeration is refused rather than merely omitted — an enumeration would have to
render the card again, and §7's card is engine-assembled from a resolution this
process still holds. An egress park is the opposite case and is
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
> `StrEnum` with exactly eight members: `PERFORMED`, `AWAITING_CONFIRMATION`,
> `REFUSED`, `AMBIGUOUS`, `AMBIGUOUS_TRUNCATED`, `NOT_FOUND`, `UNRECORDED` and
> `FAILED`.

> **Normative.** `FAILED` means the operation was **called and raised**, and the
> engine asserts nothing about whether it took effect. `UNRECORDED` means §9's row
> was not written — the store refused it, or no `route_id` could be minted for it
> (§9) — so the operation was **never called** and nothing was destroyed. The two are separate members because they are opposite statements
> about the same question — did anything happen — and a surface that rendered them
> alike would tell a user their belief might be gone when this decision guarantees
> it is not.

> **Normative.** `core/types.py` gains `RoutedListing`, the type alias naming the
> arms a routed listing may take. Its arms are homogeneous tuples of types the
> promoted surface already carries: `tuple[Belief, ...]`, `tuple[Question, ...]`,
> `tuple[SourceReadRecord, ...]`, `tuple[RecordedInvocation, ...]`,
> `tuple[PermissionDecision, ...]`, `tuple[SourceGrant, ...]` and
> `tuple[SpendTotal, ...]`. It mints no payload type of its own.

> **Normative.** `core/types.py` gains `OperationConfirmation`, frozen and
> `extra="forbid"`, with exactly three fields: `operation: RoutableOperation`, the
> resolved `subject: RoutedListing`, and `token: ContinuationToken`.

> **Normative.** `OperationConfirmation` states its own invariants as a
> `model_validator(mode="after")`, and they are not left to the type annotations:
> `subject` holds **exactly one** element — never zero, never more — and that
> element is of the arm `operation` names. A zero-element subject is a card showing
> the user nothing to approve, and a two-element one is §5's `AMBIGUOUS` case
> rendered as a confirmation, which §5 forbids performing anything for. Both
> construct under a bare `RoutedListing` annotation, so the cardinality is a
> validator or it is nothing.

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
> `outcome` is `AMBIGUOUS`, `outcome` is `AMBIGUOUS_TRUNCATED`, or `outcome` is
> `PERFORMED` on a read-only operation;
> every element of `listing`, and of a confirmation's `subject`, is of the arm
> `operation` names; a present `confirmation`'s **own** `operation` equals the outer
> `operation`; and the **tag decides the permitted outcomes**, so that
> `AWAITING_CONFIRMATION` and `REFUSED` are reachable **only** on a confirm-owed
> `operation` and `PERFORMED` beside a `listing` **only** on a read-only one. §3's
> tag is a property of the operation and is therefore derivable from `operation`
> alone, which is what lets a validator state this without a second field. The last is the one an inner-model validator cannot reach: a
> card is valid on its own terms while describing a different operation from the
> route that produced it, and a user reading "revoke this grant?" would be
> approving a `forget`. One discriminator per value is §8's rule, and two values
> carrying it must agree or the pair is not a description of one route.

> **Normative.** `TurnOutcome` gains a validator clause stating that `routed` and
> `step` are never both non-`None`. §1 ends the pipeline at a taken route, so a pass
> that routed drove no step, and an outcome carrying both would be describing two
> passes.

> **Normative.** On a pass that routed, `TurnOutcome.turn` is `None`, and this
> **partially supersedes ADR-0170 §4** in the scope the header names. A routed pass
> **owes an answer** exactly when `routed` is non-`None` and `routed.outcome` is not
> `AWAITING_CONFIRMATION`, and where an answer is owed the outcome carries a
> non-`None` `reply` **or** carries `reply` `None` with `reply_degraded` `True` —
> the same two states ADR-0170 §4 and §8 already give a pass that owes one, and
> ADR-0173 §6's third state, a partial `reply` beside `reply_degraded` `True`, is
> admitted here on the same terms. A routed pass that owes **no** answer — a routed
> park — carries `reply` `None` and `reply_degraded` `False`.

> **Normative.** What is superseded is exactly this: ADR-0170 §4's second `None`
> shape ceases to be an exhaustive account of a `None` `turn`, and its two clauses
> stated in the `turn is None` direction — that such an outcome carries no `reply`,
> and that `reply_degraded` is never `True` on it — cease to bind where `routed` is
> non-`None`. Nothing else moves. An outcome carrying **no** `routed` obeys ADR-0170
> §4 and ADR-0173 §6 exactly as before, and a **recovered** park is such an
> outcome: it refuses a `reply` after this decision as it did before.

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

### 9. A routed operation is recorded, the row is written before the effect, and it states what was decided

> **Normative.** A row is written at exactly **three** points, and at no other:
> before a read-only operation is performed; before a confirm-owed route **parks**;
> and on the `resume` that answers such a park — before the operation is performed
> where the answer is yes, and before the pass returns where it is no. A route
> whose resolution ended in `AMBIGUOUS`, `AMBIGUOUS_TRUNCATED` or `NOT_FOUND`
> decided nothing to do and
> writes no row, and a pass that declined to route writes none.

> **Normative.** So a **confirm-owed route writes two rows**, one per decision: the
> router's, that this operation on this subject was put to the user, and the user's
> answer. They are two facts about two moments, in an append-only trail that cannot
> revise the first when the second arrives — which is ADR-0192's own shape, where an
> authorisation and the act that spends it are two rows rather than one rewritten.

> **Normative.** `RouteApproval.OWED` states that **the router decided to seek the
> user's confirmation** for this operation on this subject. It does **not** state
> that a card was rendered, delivered, or seen: the row is written before the park
> is registered, so a cancellation between the two leaves an `OWED` row for a
> confirmation nobody was shown, and that is the safe direction §9's ordering
> deliberately chooses. No surface renders an `OWED` row as "you were asked".

> **Normative.** A **park that is never answered** therefore leaves exactly its
> first row. No later write completes it, and no reader treats the absence of a
> second row as a refusal, as a lapse, or as evidence about what the user saw.

> **Normative.** A row that cannot be written **stops the act it precedes**. The
> pass ends in `RouteOutcome.UNRECORDED`, the operation is not called, no park is
> registered and no token is minted. This applies to read-only members as well as
> confirm-owed ones: one ordering, one failure mode, and no partial mode in which
> some routed operations are recorded and others are not.

> **Normative.** The row states what was **decided** and never what happened —
> ADR-0186's own title, and here it is forced rather than chosen, because the row
> is written before the operation runs and a row claiming an effect would be
> claiming one that had not occurred yet. The pass's own `RouteOutcome` on
> `TurnOutcome.routed` is where what happened is reported.

> **Normative.** `core/types.py` gains `RoutedOperationRecord`, frozen and
> `extra="forbid"`, with exactly seven fields and no others:
>
> - `id: Identifier` — the row's own identity, **minted by the caller** from the
>   id factory the engine already holds injected, before `record` is called. The
>   store mints nothing: a store that minted the id could not be handed a frozen
>   record, and a retry could not name the row it was retrying.
> - `route_id: Identifier` — the identity of the **route**, minted once when the
>   route is taken and carried by every row of that route. Its uniqueness is checked
>   at **both** ends, because neither end can do it alone: at the mint (below) it is
>   unique across every **live park**, and at the store `record` refuses a row whose
>   `route_id` is already held by a **retained** row differing in `operation`,
>   `subject` or `conversation_id` — with `RoutingTrailError`, appending nothing,
>   and the act that row precedes does not proceed. Without the store's half a
>   repeating id factory would file two destructive decisions as one route while the
>   row-level `id` check passed, since the two rows' own ids differ; without the
>   mint's half the bound would defeat the store's, since a pruned row is a row
>   `record` cannot see. On a read-only route it
>   names one row; on a confirm-owed route it is what joins the `OWED` row to the
>   `GIVEN` or `REFUSED` row that answers it, and it is carried on the parked entry
>   the continuation token names so the `resume` can write it.
> - `decided_at: UtcInstant` — when this decision was taken, from the injected clock
>   (ADR-0009), never from the store.
> - `operation: RoutableOperation` — which operation the route named.
> - `approval: RouteApproval` — a `StrEnum` gaining exactly four members:
>   `NOT_OWED` on a read-only operation, `OWED` on the row written before a
>   confirm-owed route parks, `GIVEN` where the user answered a §7 confirmation
>   `True`, and `REFUSED` where they answered `False`. A confirm-owed operation's
>   row is never `NOT_OWED` and a read-only operation's row is always `NOT_OWED`,
>   stated as a two-directional validator.
> - `subject: Identifier | NonBlankEncodableText | None` — the **scalar argument**
>   §5's mapping read off the resolved candidate, or `None` where the operation
>   takes none. It is the identity the façade was called with — a `Belief.id`, a
>   `Question.id`, a `SourceGrant.source` — and never the display subject and never
>   the record's contents.
> - `conversation_id: Identifier | None` — the conversation the ask ran under,
>   `None` where the pass has none for ADR-0074 §3's own reasons.

> **Normative.** The record carries **no content**: no query, no utterance, no
> belief text, no listing, no reason, and no free text of any kind. That is
> ADR-0185 §2's ground — a trail row is a statement about a decision, not a copy of
> what the decision was about — and it is what makes the row safe to keep after the
> belief it names is destroyed.

> **Normative.** A `route_id`'s rows form a **state machine, and `record` enforces
> it** inside the same critical section, refusing with `RoutingTrailError` and
> appending nothing on any other sequence. What it enforces is exactly what it can
> see in the rows it **retains**, and never a fact about a park it is not the
> authority for. A read-only route is exactly one `NOT_OWED` row: a second row of
> any kind under a `route_id` retaining a `NOT_OWED` row is refused, an answer
> included. A confirm-owed route holds **at most one** `OWED` row and **at most
> one** answer: a second `OWED` row is refused, and a `GIVEN` or `REFUSED` under a
> `route_id` already retaining either answer is refused. Without these the trail
> could hold a `GIVEN` and a `REFUSED` for one route — two incompatible claims
> about what one person decided — or two answers to one question.

> **Normative.** An answer arriving under a `route_id` that retains **no** row is
> **accepted**, and `record` requires no `OWED` row to admit one. This is forced by
> the bound: pruning is by recording order alone (below), so a live park's `OWED`
> row can be pruned while the park is still registered and still claimable — at
> `routing_trail_max_rows` of one, a single routed read between the park and the
> user's yes is enough. Requiring the row would make a **retention** setting decide
> whether a user's approval of a live confirmation is honoured, which is a
> correctness dependency on a bound and the strictly worse failure of the two: an
> orphan `GIVEN` costs an operator one join that finds no `OWED`, where the refusal
> costs the user the operation they had just approved and leaves the park claimed,
> its slot released and nothing done.

> **Normative.** A `route_id` is minted when the route is taken — by **every**
> route, read-only ones included — and the mint is **reserved**, never merely
> checked. The reservation is taken in the **same in-memory critical section** that
> §7's ceiling slot is reserved in and that a park is registered in: under one lock
> the engine tests the candidate against every `route_id` currently **reserved** —
> those of registered parks and those of routes still in flight alike — and records
> the reservation before the lock is released. A candidate that collides is retried
> from the factory inside that same section; a small retry budget exhausting ends
> the pass in `RouteOutcome.UNRECORDED`, with nothing reserved, nothing parked, no
> row written, no token minted and the operation never called. A read-only route
> reserves too, because its `NOT_OWED` row under a live park's id would collide
> with that park's own answer exactly as a second park's `OWED` row would.

> **Normative.** A route-id reservation is **released on every path** that does not
> end in a live park, in the `finally` §7 already requires of the ceiling slot and
> beside it: the row of §9 failing to write, the id factory raising, the resolution
> raising, the pass being cancelled at any await, and any defect in the code
> between. A read-only route releases its reservation when the pass ends, whatever
> the pass ended as. A confirm-owed route holds its reservation for exactly as long
> as the park is live, and releases it in the same critical section that claims or
> evicts the park (§7). A reservation that could leak would exhaust the retry
> budget for every later route, which is the ceiling's own failure mode arriving
> through the identity instead of the slot.

**A check that is not atomic with the registration is not a check, and the window
here is wide rather than theoretical.** Between deciding an id is free and
registering the park sit §9's row write and the prune it performs — two awaits on a
durable store — so two routes can each find an empty table, each be handed the same
id by a repeating factory, and each register. Worse, the prune performed by the
second is what removes the first's evidence, so the store's retained-row rule
cannot catch what the in-memory check just missed. Reserving under the lock that
already guards §7's ceiling closes the window without adding a second lock, and it
puts the two resources a route holds — a slot and an identity — under one
acquisition and one `finally`.

**Liveness is checked where liveness lives, which is the same lesson as the clause
above read from the other side.** The store's `route_id` rule is a consistency
check over the rows it **retains**, and at a small `routing_trail_max_rows` those
rows are not a census of live routes — so it cannot be the guard against a
repeating factory, and left as the only guard it fails in the direction that costs
the user the operation. Concretely: a live `forget` park's `OWED` row is pruned, a
second park takes the same id because no row remains to conflict with, and the
first park's approval then collides with the *second* park's retained row and is
refused — after §7 has already claimed the token, so the user's yes is spent on
nothing. The park table is the state and knows exactly which ids are live, so the
reservation is where a collision is caught: before anything is parked, before a
token exists, and before a card is shown that could not be honoured.

**What survives a prune is history, not a resolution.** Two routes can still end up
under one `route_id` in the trail, where a factory repeats across a prune and no
park was live at the mint. That costs an operator a join that finds more than it
expected and costs no user an operation, which is the trade §9 makes throughout: a
bounded trail forgets, and what it must never do is forget something a live park
depends on. Reserve-and-retry is the shape ADR-0074 §1 already gives a conversation
id, and it is here for ADR-0074 §1's own reason: the factory is *injected*, so a
repeating test double, a seeded factory or a future non-random scheme makes a
collision reachable in a way probability does not answer.

**The dropped check is the mistake, not the bound.** It is tempting to exempt a
live park's `OWED` row from pruning instead, and that is the wrong half to move:
a bound with an exception is a bound an adversary chooses the shape of, and a
client that opens parks and abandons them would pin rows the bound exists to
evict. What the check was actually buying was never authority over the park —
§9 above is explicit that `OWED` does **not** state a card was rendered,
delivered or seen, so the pair was never evidence about what the user saw. It
bought consistency between two rows of one route, and every clause of that
consistency that `record` can see without being the park's authority is kept. The
park is the **state**, held in memory under the engine's own lock (§7); the trail
is the **record**, and a record that can refuse the thing it records is not one.

> **Normative.** `core/protocols.py` gains **two** Protocols on ADR-0185 §4's split,
> and the seam divides by capability. `RoutingRecorder` **writes** and can answer
> nothing:
>
> ```python
> async def record(self, record: RoutedOperationRecord) -> None
> ```
>
> `RoutingTrail` records and reads, with exactly four members on ADR-0185 §12's
> shape and no others:
>
> ```python
> async def record(self, record: RoutedOperationRecord) -> None
> async def recent(self, *, limit: int) -> tuple[RoutedOperationRecord, ...]
> async def export(self) -> tuple[RoutedOperationRecord, ...]
> async def clear(self) -> None
> ```
>
> `record` is specified once and binds both, since one concrete store satisfies
> them.
>
> `record` appends one row and returns nothing, taking the identity the caller
> minted rather than producing one. Its checks and its append are **one critical
> section**: the row-`id` equality test, the `route_id` test, the append and the
> §9 pruning happen under one transaction or one lock, so two concurrent `record`
> calls carrying a colliding `route_id` cannot both observe no conflict and both
> append. Exactly one succeeds and the other raises `RoutingTrailError`, and the
> loser's act does not proceed. A row already present under the same `id`
> **whose every field is equal to the one supplied** is not appended twice and is
> not an error, so a retried write is idempotent; a row present under the same `id`
> differing in **any** field raises `RoutingTrailError` and appends nothing, and the
> act that row precedes does not proceed. Idempotence is over the whole frozen
> record and never over the id alone: a repeating id factory would otherwise let a
> routed `revoke` be performed while the trail kept only an earlier `forget`'s row,
> which is the one failure this store exists to make impossible. `recent` answers **newest-recorded first** and refuses a `limit`
> outside `[1, 2**63)` locally and before any I/O, as ADR-0186 §3 requires of every
> bounded listing. `export` answers the whole trail in the same order and is bounded
> only by ADR-0085 §8c's payload limit. `clear` destroys every row, for ADR-0007's
> deletion right.

> **Normative.** The routing stage of §2 is injected with a **`RoutingRecorder`**
> and holds no `RoutingTrail`. Nothing but a future hub-owned read surface (§11)
> holds one. Structural typing means the one `permissions/` store satisfies both,
> so the composition root passes one object to the stage and to that surface alike;
> what the stage cannot do is *name* `recent`, `export` or `clear`.

**The split is ADR-0185 §4's move, and here it forecloses something worse than a
cursor.** There the capability removed from the driver was the ability to *read*
the trail, because a queryable read trail is the cursor ADR-0093 §5 forbids. Here
the stage must write, and the capability removed is the same one plus `clear` —
which means a routing stage handed the whole trail could **erase the record of its
own decisions**. `clear` exists for ADR-0007's deletion right and belongs to the
surface that answers to the user; a stage whose acts the rows are *about* is the
last thing that should be able to call it. Making that a `mypy --strict` failure
rather than a review note is ADR-0185 §4's own standard on ADR-0097 §3's argument:
"It holds no store handle, and that is the scope limit rather than a rule about it
… Here it is a type."

**It costs two triads and that is named rather than discovered.** Two suites, two
fakes, two binding classes; the `RoutingRecorder` half is one member, and §12 binds
its suite to **both** fakes, which turns part of the cost into evidence that the
store really does satisfy the narrow seam — the arrangement ADR-0185 §12 already
uses for its own pair.

> **Normative.** `core/errors.py` gains `RoutingTrailError`, a direct subclass of
> `AssistantError` — **one class rather than several**, as `ReadTrailError` is one
> class rather than two — and it is what every member of both Protocols raises on a
> durable failure. No member raises a bare `Exception`, and no member orphans a
> resource it acquired when the call is cancelled (ADR-0060 §1).

> **Normative.** `RoutingRecorder` and `RoutingTrail` are **new Protocols and each
> owes the full triad** — Protocol, shared conformance suite, and canonical fake in
> `ai_assistant.testing` — in the change that adds them (`CONTRIBUTING.md` →
> "Adding a Protocol", ADR-0137 §3). Neither is an internal seam of `permissions/`.

> **Normative.** `core.config.Settings` gains `routing_trail_max_rows`, an
> `_IntegerSetting` defaulting to `200_000`, `gt=0` and `lt=2**63`, validated at
> load — the shape and the number `source_read_trail_max_rows` already carries,
> because a routing row is smaller than a read row and the two trails are read by
> the same kind of operator. The trail is bounded by it, pruned
> earliest-recorded-first inside `record`'s critical section, **with no spelling for
> "unlimited"** (ADR-0185 §6).

> **Normative.** Pruning is by recording order alone and takes no account of a
> route's state: an unanswered park's `OWED` row is pruned at the bound like any
> other, and pruning it neither evicts the park, releases its slot, nor makes its
> token unresolvable. The park is in memory and the trail is the record rather than
> the state, so a pruned row costs history and never costs a resolution — which is
> true only because the state machine above admits an answer under a `route_id`
> retaining no row. The two clauses are one decision read from its two ends, and a
> lane may not implement one without the other.

> **Normative.** `AssistantEngine` gains **no method** for this trail in this
> decision, and the trail is therefore unreachable from the CLI and from a browser.
> ADR-0177 §1's count of thirty does not move.

> **Normative.** The routing trail is a **fourth** row kind and joins neither of the
> two ADR-0186 §10 partitions: a routed operation is never a `PermissionDecision`
> and never a `SourceReadRecord`, and no lane widens `recent_decisions`,
> `export_decisions`, `recent_reads` or `export_reads` to return one.

> **Normative.** The routing trail is a **Tier 1 local store**. ADR-0155 §1's
> residency clause governs it, so no component places any part of it in a service
> another party operates; its file lives under `Settings.data_dir` and is created
> owner-only (ADR-0004 §4, ADR-0084 §9). The hub owns it exclusively, as it owns
> every other database in the data directory (ADR-0083 §1, §10), and no interface
> adapter opens it. `ai-assistant-purge` destroys it as part of destroying the data
> directory, with no per-store step and no new clause: ADR-0126 §1's act "carries
> no inclusion list and no exclusion list … and it opens no store to empty it", and
> no lane adds one for this store.

> **Normative.** The primary production implementation lives in **`permissions/`**,
> beside `SqliteAuditTrail` and `SqliteSourceReadTrail`. It is not built in
> `orchestration/`, which consumes contracts and holds no store today, and the
> stage of §2 reaches this one by injection like every other.

**The classification is stated rather than inferred, and it follows either way.**
ADR-0155 §1's second clause decides membership by *where this system persists a
value* rather than by what it contains, so a store whose file is under `data_dir`
is inside the residency clause whether or not this ADR says so — ADR-0185 §9's own
reason for saying it anyway is that a new store which omitted to would be a store
nobody had classified. The rows make it worth being findable: they carry
conversation ids and the subjects of model-selected operations against the owner's
own memory.

**And `permissions/` is where every decision trail this system keeps already
lives.** ADR-0004 §7 charters the subsystem for the audit trail, ADR-0185 §4 placed
the read trail there on ADR-0097 §3's argument, and ADR-0192's `RecordedInvocation`
rides `AuditTrail` in the same package. Being a **fourth row kind** is a statement
about what a row *is* — that it is neither of ADR-0186 §10's two — and never about
which package the store is built in; the two questions are answered separately
because ADR-0186 §10's partition would otherwise read as a placement rule it never
was.

**Recording it is the delegated call, and this is why it went that way.** Every
other place a model's choice reaches an effect in this system leaves a durable
record: a plan's steps become `StepExecution` rows, a permission ruling becomes a
`PermissionDecision`, a source read becomes a `SourceReadRecord`, an authorised
call becomes a `ToolInvocation` (ADR-0192), a memory write becomes a
`MemoryDecision`. A routed `forget` would be the sole exception — and it is the one
that destroys the only evidence of itself, since `AssistantEngine.forget` "relays
`MemoryStore.delete` and nothing more". Leaving the new door unrecorded because the
old door is would be reasoning from the gap rather than from the rule.

**Writing the row before the act it precedes is this repository's own pattern
rather than a new one.** `ConversationTurn`'s docstring states it for the
conversation index: "no episode can exist for a conversation without its id having
been recorded here first (§8)", which is what makes that index "an intent log". The
alternative ordering — perform, then record — cannot be made true by any amount of
care: the two writes are to two stores, and a failure or a cancellation between them
leaves a destroyed belief with no row, which is precisely the state a trail exists
to make impossible. Ordering it the other way inverts the residual into the safe
direction: a cancellation between the write and the call leaves a **row for an
operation that did not happen**, and an over-recorded trail is a trail an operator
can reconcile, where an under-recorded one is a trail nobody can trust. ADR-0060
makes a cancelled write's effect indeterminate and requires the cancellation to
propagate; both hold here, and this ordering is what makes the indeterminacy fall on
the row rather than on the act.

**The row therefore states no outcome, and that is not a shortcut.** A row written
before the call cannot say whether the call succeeded without being rewritten, and
rewriting is what an append-only trail is not. ADR-0186's title is the rule it lands
on — a row states what was decided rather than what happened — and the pass's own
`RouteOutcome` is where "what happened" belongs, because that is the value the user
is looking at.

**Two rows for a confirm-owed route is what that ordering costs, and it is the
honest shape rather than a concession.** A single row could only be written at one
of the two moments, and each choice loses something real. Written at the park, it
would have to guess the answer or leave `approval` unset for a row that may never be
completed. Written at the resume, an abandoned park would vanish from the trail
entirely — and "the assistant proposed to delete a belief and the user walked away"
is exactly the sequence an operator wants to be able to see. Two rows joined by
`route_id` state both moments and invent neither, which is why ADR-0192 reached the
same shape for an authorisation and the act that spends it.

**Refusing to perform on a failed write costs a routed read during a trail outage,
and it is still the right side.** The alternative is a rule that records
confirm-owed operations and best-efforts the rest, which is two orderings, two
failure modes and a branch every reader must hold. One rule is cheaper to obey and
cheaper to test, and a hub whose routing trail is unwritable has a fault the
operator should see rather than route around.

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
badly by answering it incidentally. The two unreached members are specified now
rather than added later for the reason ADR-0185 §12 specified them: widening a
ratified Protocol is a breaking change, and a store built against a two-member
seam would be rebuilt against a four-member one.

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
> rather than reading it off a turn that is not there.

> **Normative.** The captured episode of a routed pass carries **no part of the
> routed account**: not the listing, not the display subject, not the scalar
> argument, and not the candidates. This is §6's second sentence made mechanical
> rather than hoped for — a conversation's recent turns are retrieved into the next
> turn's prompt (ADR-0074 §5, ADR-0158 §5), so a capture that folded a routed
> listing into the episode would deliver the routed result to a model one turn
> later, satisfying every same-pass clause of §6 while breaking §6. Whether the
> composed **reply** joins the captured episode is #1314's ground and is untouched
> either way.

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
> tool, designates no seam, changes no method **signature** on `AssistantEngine`,
> and adds no `core` name other than §8's five, §9's two types, its two Protocols
> and its one error class. It does move one method's **contract** — `resume`'s, in
> the two sentences §7 names and §13 records — and that is not the same claim: a
> signature is what a caller compiles against, a contract is what it may rely on,
> and this ADR moves the second and not the first. A lane needing any of those
> needs its own change and, where golden rule 5 reaches it, its own ADR.

- **Milestone 27 — multi-step plan driving** (#242). ADR-0170 §5's "at most a
  plan's first step is driven" is untouched. A routed ask drives no plan step at
  all, so this decision neither depends on that limit nor relaxes it.
- **A read surface for the routing trail.** §9 mints the store and no engine
  method. The surface is its own decision, on ADR-0185 → ADR-0186's sequence, and
  should weigh whether four trails want four pairs of operations.
- **A second varying argument on any routed operation**, and therefore a route
  envelope carrying more than `operation` and `query`. §3's one-argument clause is
  the boundary, and moving it is a decision rather than an extension.
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
- **`grant` and `answer`, and every other operation with a second varying
  argument.** `AssistantEngine.grant(source, *, scope: Sequence[GrantScope])` needs
  a scope, and `answer(question_id, *, accept: bool)` needs the accept/reject
  decision itself. §5's lookup resolves one identity and §7's confirmation is a
  yes/no, so neither argument has a source that is not the model inventing it —
  and a model-invented `scope` is a model authoring an authorisation, which is
  ADR-0102's ground and not a routing detail. Mapping the confirmation's `approved`
  onto `accept` is refused for the same reason it looks tempting: it fuses "may I
  do this" with "what should I do", so a user declining a correction and a user
  declining to be asked would be the same wire value. Both are named as the first
  candidates for a widening once that argument's design exists, and #1312's "yes, I
  did move" example is what that widening buys.
- **`beliefs`, `learn`, and the operations §3 leaves out.** The widening rule is how
  they arrive, and each arrival owes §3's five conditions stated in its own lane's
  ADR.
- **The router's prompt text and which model answers.** `orchestration`'s to write,
  under §4's constraints on what it contains.

### 12. What the implementing lanes owe

This decision is larger than one lane, and ADR-0173's implementation across three
PRs is the precedent for an ADR that lands in more than one. Where it may be cut
is ADR-0137 §2's, and that section decides the cut here rather than leaving it to
the lanes.

> **Normative.** **One lane** lands all of it but §10's renderings: §8's `core`
> surface, §9's two triads (`RoutingRecorder`'s and `RoutingTrail`'s — each
> Protocol, shared conformance suite and canonical fake), the one `permissions/`
> store that satisfies both, the routing stage of §2, the engine wiring that
> consumes it, and §8's `PROTOCOL_VERSION` bump. The contracts are **not** landed
> ahead of the router, and the store is not landed ahead of it either.

> **Normative.** The shared suite for `RoutingRecorder` binds to **both** fakes, as
> ADR-0185 §12's pair does, so the narrow seam is evidenced rather than asserted.

**Why one lane and not the two this ADR first wrote.** ADR-0137 §2 pairs a triad
with its **primary production implementation**, and it defines the term against the
obvious reading: "Primary means the consumer whose demands shape the contract, not
the one that is cheapest to write … What pairs is the triad's **code** with its
first real caller." `RoutingRecorder`'s first real caller is the routing stage, not
the `permissions/` store that satisfies it — the store is the *provider*. A lane
landing both triads and the store first, with the router behind them, is precisely
the sequence §2 exists to forbid: "A contract whose only exercise is its own
conformance suite hardens before anything has tried to use it in anger, and the
first real consumer must then either bend around a shape that is already ratified
or reopen a settled decision." The store rides in the same lane because a stage
wired to a fake is not a caller in anger either.

**ADR-0185 §12 is the ratified precedent for exactly this shape, and it is one
lane.** Two Protocols split by capability, one `permissions/` store satisfying
both, and consumers in another subsystem: "The implementing lane ships both triads
and the store in one change with its primary producer, under ADR-0137 §2's
contract-seam exception; it wires the recorder into all three drivers." This
decision follows it rather than opening a second way. ADR-0137 §1's bound is
therefore not read as splitting the store off from the contracts it implements —
that reading would put the two triads in a lane with no production implementation,
and would land the contracts ahead of the consumer §2 pairs them with, which is
the sequence §2 exists to forbid.

`RoutingTrail`'s own first caller does not exist yet — §11 defers the read surface
— and that is ADR-0185 §12's shape rather than a gap: it minted `SourceReadTrail`
with `recent` and `export` and gave the user nothing to read them with, for the
reason §9 gives above. What §2 requires is that a contract with a consumer land
with it; it does not require inventing one for a contract whose consumer is
deliberately deferred.

**The cost is named rather than discovered.** This is a large lane — two triads,
one store, one stage, the engine wiring and a `core` surface, across `core`,
`permissions` and `orchestration`. ADR-0137 §2 is explicit that its widening of
"one subsystem per change" is for exactly this and "does not create a general
licence for cross-subsystem lanes"; nothing else in this decision is cited toward
one. What §10's renderings buy by staying separate is stated below: they are a
consumer group and not a second decision.

> **Normative.** That lane ships tests pinning: `RoutedOperation`'s
> validator in **both** directions on each of the five invariants, the fourth
> asserted with a `confirmation` whose `operation` differs from the outer one and
> which is otherwise wholly valid, and the fifth with a **read-only** `operation`
> carrying `AWAITING_CONFIRMATION` beside a wholly valid one-element confirmation,
> and with the same operation carrying `REFUSED`; `OperationConfirmation`'s own validator against
> a **zero**-element subject, a **two**-element subject, and an element of the
> wrong arm; the
> `routed`/`step` mutual exclusion; and §8's widened `TurnOutcome` shape across
> **all four** of its routed cases — a routed non-park carrying a `reply` beside a
> `None` turn; the same pass with `reply` `None` and `reply_degraded` `True`, which
> is the routed composition failure §10 requires and the case a validator written
> as "a routed pass carries a reply" silently forbids; a routed park carrying
> neither; and a **recovered** park still refusing a reply, so the supersession is
> pinned as narrow rather than as a relaxation.

> **Normative.** The same lane ships §4's decline tests on ADR-0176 §1's own model:
> a parameterized test that `1`, `1.0`, `"true"`, `"yes"` and JSON `false` are each
> **not** the `no_operation` marker and the JSON boolean `true` is; and a test that
> an `operation` value which is not a `RoutableOperation` member declines rather
> than resolving onto a near match.

> **Normative.** The same lane ships §4's **failure**-decline tests, one per class
> and each deterministic: the provider raising `ModelError`; a blank completion; a
> completion that is not JSON; a well-formed envelope missing a required `query` on
> a member that needs one; and a well-formed envelope carrying a member outside
> §3's enum. Each asserts the same two things — **no route is taken**, and the
> ordinary pipeline runs to its own answer — so the pass is indistinguishable from
> one the router declined outright. These are the cases that separate a decline
> from an error: an implementation letting `ModelError` propagate fails an ordinary
> ask that routing was never meant to touch, and it passes every marker-strictness
> and unknown-operation test above.

> **Normative.** The same lane ships a test that a routing prompt assembled for an
> utterance is **byte-identical** whether the store holds a hostile record or none,
> pinning §4's last clause structurally rather than by inspection.

> **Normative.** The same lane ships §6's tests under a **deliberately contradictory
> provider**: a fake composer asserting it was handed only a `RoutableOperation` and
> a `RouteOutcome`, over a routed `recent_reads` whose listing contains a record
> whose fields carry the composer's own container syntax, asserting that no part of
> the listing appears in the assembled prompt. A test asserting only that the
> composer was called does not satisfy this clause.

> **Normative.** The same lane ships §6's **two-turn** test, which is the only one
> that can fail on a capture that folds the routed account into the episode: a
> routed `recent_reads` over a hostile listing, captured; then a second, ordinary
> ask in the same conversation, asserting that no span of that listing appears in
> the second turn's assembled prompt — the planner's and the composer's alike. A
> one-turn test cannot see this failure and does not satisfy this clause.

> **Normative.** The same lane ships §5's three resolution cases — none, one, more
> than one — asserting that the many-candidate case performs **nothing**; the
> truncation boundary asserted on **both** sides, a lookup of exactly
> `DEFAULT_PAGE_SIZE` candidates reaching `AMBIGUOUS` and one of
> `DEFAULT_PAGE_SIZE + 1` reaching `AMBIGUOUS_TRUNCATED` over a listing of exactly
> the bound, which is the pair that fails on an off-by-one and on an
> implementation that never distinguishes the two; §5's
> mapping asserted per confirm-owed member, that the façade was called with the
> scalar identity and never handed the record; and §7's park-and-resume pair
> asserting that a refused resume performs nothing and that a routed park does not
> appear in `pending_confirmations`.

> **Normative.** The promoted surface's contract moved (§7, §13), so the lane
> landing §8 ships the coverage that pins the move as **narrow**, and ships it in
> the shared `AssistantEngine` conformance suite rather than in one
> implementation's own tests, because every implementation of that surface owes it:
> a routed park resumed `True`, asserting `step` `None`, `routed` present and the
> operation called; the same park resumed `False`, asserting
> `RouteOutcome.REFUSED`, that **no** `PermissionDeniedError` is raised, that the
> operation was not called and that no `PermissionDecision` was recorded; and,
> beside them in the same suite, an ordinary parked step resumed `False`, asserting
> that it still raises `PermissionDeniedError` and that its outcome still carries a
> `step`. The third case is not decoration: without it the suite pins the new
> behaviour and not its scope, and an implementation that stopped raising on every
> refusal would pass.

> **Normative.** The same lane ships §7's one-shot claim as **concurrency** tests
> rather than sequential ones: two `resume` calls on one token raced with
> `approved` `True` on both, and raced with `True` and `False`, asserting in each
> case that the operation was called at most once, that exactly one `GIVEN`-or-
> `REFUSED` row exists for that `route_id`, and that the loser raised
> `UnknownContinuationError`. A test that resumes twice in sequence does not
> satisfy this clause. It also ships the ceiling case: routed parks accumulated to
> `max_outstanding_confirmations` and one more, asserting the same backpressure a
> step-driving turn meets there and that no park was registered for the refused one;
> a reservation taken and then failed before registration — the trail write raising,
> and the pass cancelled at that await — asserting that a later routed park is
> admitted, which is the only assertion that fails on an implementation releasing
> the slot only on resolution; and a park held past its lifetime, asserting that its
> slot is released, that its token then raises `UnknownContinuationError`, and that
> a fresh routed park is admitted at a ceiling of one.

> **Normative.** The lifetime's expiry is pinned by advancing the **injected clock**
> and then calling `resume` **directly** — seeking no capacity and enumerating no
> confirmations first — asserting `UnknownContinuationError` and that the operation
> was not called. A test that reclaims the slot before resuming does not satisfy this
> clause, because it passes against an implementation whose expiry is only ever
> noticed by housekeeping. The boundary is asserted on both sides of the lifetime,
> and `routed_confirmation_ttl` is asserted refused at load for `None`, for zero and
> for a negative duration.

> **Normative.** The same lane ships `record`'s conflict cases: the same `id`
> presented with a differing field raises `RoutingTrailError`, appends nothing, and
> the act it precedes does not proceed — asserted with the operation's store
> observed untouched; the same for a `route_id` already held under a different
> route. The identical-record retry is asserted beside them, so idempotence is
> pinned as over the whole record rather than over the id.

> **Normative.** The same lane ships the route state machine as conformance cases,
> each asserting `RoutingTrailError` and an unchanged trail: `GIVEN` after
> `REFUSED` and `REFUSED` after `GIVEN`; a second `GIVEN` and a second `REFUSED`; a
> second `OWED`; and a second row of any kind — an answer included — on a route
> retaining a `NOT_OWED` row. The two valid sequences — `OWED`→`GIVEN` and
> `OWED`→`REFUSED` — are asserted beside them.

> **Normative.** The same lane ships the **admitted** case beside those refusals,
> and it is the one that fails on the natural wrong implementation: a `GIVEN`, and
> a `REFUSED`, recorded under a `route_id` the trail retains **no** row for, each
> asserted to append. A suite that only pins the refusals passes against a `record`
> that requires an `OWED` row.

> **Normative.** The same lane ships the reservation half of §9's `route_id` rule
> under a **deliberately repeating** id factory, and ships it as a **concurrency**
> test, because a sequential one passes against a check-then-register
> implementation. At `routing_trail_max_rows=1` and a ceiling admitting two parks,
> two confirm-owed routes are raced while the factory yields one id `r`: assert
> that at most one park is registered under `r`, that the other either retried onto
> a different id or ended `UNRECORDED` with nothing parked and no token minted, and
> that resuming the first, still-live token then performs its operation and appends
> its `GIVEN` row. The interleaving the test must be able to produce is the one §9
> names: both routes observing an empty table, the first's `OWED` row written and
> then pruned by the second's, and both registering. A suite pinning only the
> store's retained-row conflict passes against an implementation with no
> reservation at all.

> **Normative.** The same lane ships the reservation's release paths beside §7's
> slot-release cases and with the same assertion shape: a route whose §9 row write
> raises, and a route cancelled at an await before registration, each followed by a
> later route asserted to obtain an id from a factory yielding the **same** value —
> which fails against an implementation that releases the identity only on
> resolution. A read-only route's reservation is asserted released when its pass
> ends, whatever it ended as.

> **Normative.** The same lane ships the bounded-trail park→prune→resume path
> end-to-end at `routing_trail_max_rows=1`: a confirm-owed route parks and records
> `OWED`; a routed read-only operation records its `NOT_OWED` row and prunes the
> `OWED`; the still-live token is then resumed with `approved` `True`, asserting
> that the operation **is** performed, that the pass returns `PERFORMED`, and that
> the `GIVEN` row is appended. This is the case a bound and a state machine written
> in one change can each pass alone and fail together, so it is required of the
> one lane rather than left to whichever half of it a reader thinks owns the case.

> **Normative.** The same lane ships `record`'s atomicity as a **concurrency** test
> in the shared conformance suite, so every implementation pays it: two `record`
> calls raced with a colliding `route_id` and distinct row ids, asserting exactly
> one appended row and one `RoutingTrailError`. A sequential test of the same pair
> does not satisfy this clause, because the check-then-append implementation it is
> written against passes sequentially.

> **Normative.** The same lane ships §9's ordering tests, and they are the
> ones that fail on the plausible wrong implementation: a `RoutingRecorder` double
> whose `record` raises, asserted over a confirm-owed route the user approved
> (nothing destroyed, no operation called, outcome `UNRECORDED`), over the routing
> pass of a confirm-owed route (no park registered, no token minted, outcome
> `UNRECORDED`), and over a read-only route (the operation not called); and a
> `record` double that observes the operation's store to be untouched at the moment
> it is called, which is the only assertion that fails on an implementation that
> performs first and records after.

> **Normative.** The same lane ships the two-row lifecycle: a confirm-owed route
> answered `True` leaving an `OWED` row and a `GIVEN` row sharing one `route_id`;
> answered `False` leaving `OWED` and `REFUSED`; a park **never answered** leaving
> exactly the `OWED` row and no other; a read-only route leaving exactly one
> `NOT_OWED` row; and an `AMBIGUOUS`, an `AMBIGUOUS_TRUNCATED` and a `NOT_FOUND`
> route each leaving **none**.
> It also ships a row asserted to carry no query, no utterance and no record
> contents, and `RouteApproval`'s two-directional validator against the tag.

> **Normative.** The same lane ships §9's residency clause as a test rather
> than as prose: the store's file is created **under `Settings.data_dir`** and
> **owner-only**, asserted on the mode the platform reports, and no path outside
> that directory is opened. It is the one clause of §9 that a working store can
> violate while every other test passes.

> **Normative.** The same lane ships the discrimination `UNRECORDED` exists for: an
> `UNRECORDED` pass and a `FAILED` pass over the same routed `forget`, asserting
> that the store was untouched on the first and called on the second, so a surface
> cannot render the two alike without failing a test.

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
`None`". §8 above admits routed passes in which `turn` is `None` and an answer is
nevertheless **owed** — carrying a `reply`, or carrying `reply` `None` beside
`reply_degraded` `True` where composing it failed. A reader holding only ADR-0170 would
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

**ADR-0052 §3 — a second record is owed on the same ADR, and it is a partial
supersession.** That section ruled that a resumed step's outcome "is what a resume
is *for*, and it is always present", and that sentence stands on the promoted
surface today: `core/protocols.py`'s `AssistantEngine.resume` docstring reads "The
step is what a resume is for and is always present". §7 above creates a resume
with no step at all, so what §3 decided is **replaced** in the case §7 creates
rather than merely read too widely: a reader acting on §3 does not act identically
before and after, which is ADR-0070 §1's line between the two, and partial
supersession is the sanctioned form for replacing part of an earlier ADR
(ADR-0070 §3). It is **partial** and it is narrow:
every resume that continues a parked step is ruled exactly as ADR-0052 §3 ruled
it, and the clause fails only where `TurnOutcome.routed` is present. ADR-0084
already partially superseded §3's *placement* claim — that the widened
`TurnOutcome` sits outside contract surface — and this pair is added beside that
one rather than in place of it (ADR-0070 §4).

**ADR-0042 §4 — a record is owed, and it is a partial supersession.** That section
ruled how a confirmation's answer becomes a ruling: `ActionPolicy.resolve` "is what
turns `approved` into an `ALLOW` or `DENY` ruling, and only `approved=False → DENY`
is guaranteed". §7 above answers a routed park with no `ActionPolicy.resolve` call
and no `PermissionDecision`, so an `approved` of `False` becomes no ruling at all
and raises no `PermissionDeniedError`: the guarantee's subject is absent rather
than its value different, which is again a replacement in a named case and not an
over-wide reading. Partial and narrow in the same way — a `resume` answering a
parked step is ruled exactly as before — and §4's account of what an adapter may
**not** do, author the permission outcome, is untouched and binds the routed card
of §7 as hard as it binds a tool's.

**ADR-0085 §9 — no record is owed, and this one is worth stating rather than
omitting.** Its per-method table declares the failures each method may raise, and
`PermissionDeniedError` stays among `resume`'s: every step-driving resume still
raises it on a refusal, and the clause declares a method's failure **set** rather
than guaranteeing that some particular input produces one. No sentence of §9
becomes false or reads more widely than it holds, so ADR-0082 §1's test comes out
the other way and nothing is taken — recorded here because a reader checking the
records above will look for one on the ADR that ratified the surface, and because
ADR-0082 §1 forbids a record demanded on book-keeping grounds alone. That
the two moving sentences trace to ADR-0052 §3 and ADR-0042 §4 rather than to
ADR-0085 is ADR-0085 §3's own doing: it omits the docstrings deliberately and
states that their obligations are ratified elsewhere, naming the two it does carry
(§1's and §7's), neither of which is either of these.

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
engaged, which is a claim about routing and not about them). ADR-0084 §7 (§7
above cites its unresolvable-token rule and obeys it whole — a routed park's
unknown, expired, already-claimed and cross-restart token each yield
`UnknownContinuationError` and never a denial, which is §7's own instruction
applied to a new kind of park rather than widened). ADR-0186 §10 (its
partition is a rule about the relation between two named trails and is restated,
not widened, by §9's fourth row kind; ADR-0192 already added a third without
disturbing it). ADR-0185 §§2, 4, 6, 9 and 12 (§9 follows their shapes — the
capability split, the record-carries-no-content ground, the bound with no unlimited
spelling, the residency and ownership clauses, and the store's member shape; it
changes none of their clauses). ADR-0073 §5 (§7 binds it whole). ADR-0084 §8 (§8's `RouteOutcome`
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

**The four records — on three ADRs — are stated here in their exact form and are
not made by this change** (ADR-0026 §6, ADR-0030 §6, ADR-0032 §8): writing
"amended by ADR-0197" onto a ratified ADR while ADR-0197 is only `Proposed` is the
state claim ADR-0019 forbids. The lane that ratifies this ADR makes them, and no
other lane does. ADR-0052 takes two of the four, in two different forms, and the
difference is not a slip: a **supersession** pair accumulates on a leading-token
`Status` line (ADR-0070 §4), where an **amendment** qualifier is excluded from one
(ADR-0082 §2) and lives in the note alone.

- **ADR-0170.** Its `Status` line, which today reads `Partially superseded by
  ADR-0173 (…)`, gains this ADR's pair on the same line without dropping ADR-0173's
  (ADR-0070 §4): `and ADR-0197 (§4's second None shape and its two clauses stated
  in the "turn is None" direction, each only as it reaches an outcome carrying
  TurnOutcome.routed)`. It gains an appended dated header note recording the
  supersession's scope and its ground, ending `Refs #1623, ADR-0197 §8, §13`.
- **ADR-0052.** Its `Status` line, which today reads `Partially superseded by
  ADR-0084 (…)`, gains this ADR's pair on the same line without dropping
  ADR-0084's (ADR-0070 §4): `and ADR-0197 (§3's clause that the step "is what a
  resume is for, and it is always present", only as it reaches a resume whose
  TurnOutcome carries routed)`. No **amendment** qualifier is written on that line
  for the §1 record, because the line is led by `Partially superseded by`
  (ADR-0082 §2). Both records go in one appended dated note: `Amended and
  partially superseded: <ratification date> by ADR-0197 — §1's "the confirmations
  a user may still answer" is true of every confirmation §1's algorithm ranges
  over and does not reach ADR-0197 §7's routed park, which holds no execution, no
  step and no recorded CONFIRM for §1's four steps to recover; nothing §1 decided
  changes. §3's "the step … is always present" is superseded only where
  TurnOutcome.routed is present: ADR-0197 §7's routed resume carries step None,
  and every resume continuing a parked step is ruled as §3 ruled it. Refs #1623,
  ADR-0197 §7, §13.`
- **ADR-0042.** Its `Status` line, which today reads `Partially superseded by
  ADR-0084 (…)`, gains this ADR's pair on the same line without dropping
  ADR-0084's (ADR-0070 §4): `and ADR-0197 (§4's guarantee that approved=False
  becomes a DENY ruling, only as it reaches a resume answering a routed park)`. It
  gains an appended dated note recording that scope and its ground — that ADR-0197
  §7 consults no ActionPolicy and records no PermissionDecision for a routed park,
  so a refusal is returned as RouteOutcome.REFUSED and raises no
  PermissionDeniedError, while §4's rule that an adapter never authors the
  permission outcome is untouched — ending `Refs #1623, ADR-0197 §7, §13.`

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
- **A routed park expires, spends a scarce slot until it does, and does not survive
  a restart.** The user repeats one sentence after a restart or an expiry; a client
  that asks the assistant to forget things and never answers meets the ceiling that
  already exists rather than a new one; and a token lost in flight costs a wait
  rather than a permanently held slot. Two settings' worth of lifecycle for a park
  nobody can enumerate is the price of not building a second durable park store,
  and §7 states the trade rather than hiding it.
- **A hub whose routing trail cannot be written routes nothing at all**, reads
  included (§9), and says so with its own outcome — `UNRECORDED`, which states that
  nothing happened, as against `FAILED`, which states that something was called and
  raised. That is one failure mode rather than two and an operator sees it rather
  than routing around it, and the price is that a trail fault takes a capability
  with it. The ordinary pipeline is unaffected: an unroutable ask is an
  ask that plans, which is what it did before this decision.
- **A correction spoken in words still does not reach memory.** `answer` and `grant`
  are outside the first vocabulary because each takes a second argument no query
  resolves (§3, §11), so #1312's "yes, I did move" is not what milestone 26
  delivers. The widening rule is the route back, and what it waits on is a design
  for that argument rather than a further decision about routing.
- **Revisit if** an operation worth routing needs a second varying argument often
  enough that §3's one-argument boundary is the thing in the way; if a routed
  confirmation becomes expensive for a user to reconstruct,
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
