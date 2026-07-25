# 66. A completion request must end with a turn awaiting an answer

- Status: Proposed
- Date: 2026-07-24
- **This is a contract change.** It adds a precondition and a `Raises:` clause to
  `ModelProvider.complete` in `core/protocols.py`, binding every implementation,
  and it extends that Protocol's shared conformance suite and canonical fake.
  Golden rule 5 therefore applies: this ADR ships as **its own PR, ratified ahead
  of any implementation** (ADR-0015 §5). It is reviewed while still `Proposed`,
  so a finding can still change the decision, and flipped to `Accepted` on merge
  — `CONTRIBUTING.md`, "Contract ADRs land before their implementation". This PR
  is docs-only; the implementation is a separate lane, and until it lands the
  rule is a decision on record and not yet text in `protocols.py`.
- Refs: issue #351 (the defect), ADR-0011 (the `retryable`/`routable` taxonomy),
  ADR-0013 §5 (a non-routable failure is not routed off), ADR-0047 (the
  model-backed planner, today's only caller), ADR-0060 §§2, 5 (binding a
  Protocol versus enforcing it), ADR-0061 (model agnosticism is a tested
  property), ADR-0062 §2 (`ConfigurationError` versus `ModelError`).

## Context

`ModelProvider.complete(messages)` means "produce the assistant's next message
given the conversation so far". `PydanticAIProvider` implements it by
translating our flat `Message` list into a pydantic-ai history and calling
`Agent.run(user_prompt=None, message_history=history)`.

**If the history already ends on an assistant turn, no request reaches the model
and the trailing assistant message is returned as the reply.** Verified while
drafting this ADR, not taken on report:

```python
p = PydanticAIProvider(default_model=TestModel(custom_output_text="MODEL WAS CALLED"))
await p.complete([
    Message(role=Role.USER, content="u"),
    Message(role=Role.ASSISTANT, content="cached reply"),
])
# -> Message(role=ASSISTANT, content="cached reply")   "MODEL WAS CALLED" never appears
```

The mechanism sits above the vendor layer: `_to_model_messages` renders an
assistant turn as a `ModelResponse`, and `Agent.run` treats a history whose last
entry is already a response as a finished run, so it returns that response's
output without a round trip. Re-running the case through the two-vendor request
recorder in `tests/models/vendor_stacks.py` confirms it on both stacks —
`recorder.bodies == []` and `reply.content == "cached reply"` for Anthropic *and*
OpenAI. Nothing goes on the wire.

Three further facts, each checked rather than assumed, because they fix the
shape of the rule:

- **The trigger is precisely a trailing assistant turn, not "a trailing
  non-user turn."** A history ending on a `Role.SYSTEM` message *does* call the
  model — system and user turns both group into a `ModelRequest`, and a request
  is what `Agent.run` still needs answering. A rule phrased "must end on
  `Role.USER`" would therefore forbid a legitimate call that works today.
- **A history consisting of a single assistant turn echoes too.** The defect is
  about what the history *ends* with, not about whether a user ever spoke.
- **It is not reachable in production today.** The only caller of `complete()`
  outside the `models` package is `ModelBackedPlanner.plan` in
  `planning/planner.py`, and its `conversation` always ends on `Role.USER`: the
  repair path appends the model's reply and a `_repair_prompt` user turn
  together, never the reply alone. `RoutingProvider` and `RetryingProvider` are
  the other callers, and they only forward whatever they were handed.

### What makes it worth a decision now

Two things, neither of which is "a bug is waiting to happen".

**The contract is silent, and the two implementations already disagree.** The
canonical `FakeModelProvider` does *not* echo: handed the same
`[USER, ASSISTANT]` history it records the call and returns its configured reply,
verified. So a subsystem developed against the fake — which is what
`ai_assistant.testing` exists for — gets a model call, and the same code in
production gets its own input back. That is exactly the outcome the fake's
docstring says it exists to prevent: "code exercised with this fake cannot pass
on input … differently than it would against the real provider." The shared
conformance suite cannot catch the divergence, because the Protocol promises
nothing either way.

**The suite has already asked for this ADR.** `model_provider_contract.py` ends
with a standing note:

> NOTE: empty-conversation handling is deliberately *not* asserted here. The
> ModelProvider Protocol says nothing about empty input, so requiring it to
> raise would silently widen the contract (CLAUDE.md golden rule 5 — that needs
> an ADR, not a test).

`complete()` has two malformed-argument shapes, both rejected in practice by
nobody's promise: the empty list, which both implementations already refuse with
a bare `ModelError`, and the answered history, which one implementation echoes
and the other completes. Deciding one and not the other would leave the Protocol
promising the exotic case and silent on the trivial one.

## Decision

### 1. `complete()` refuses a conversation that is not asking for an answer

We will state on `ModelProvider.complete` in `core/protocols.py` that
`messages` must be a conversation **awaiting an assistant reply**, and that a
conversation which is not one raises `ModelError`:

> `messages` must be non-empty and must not end with a `Role.ASSISTANT` turn. A
> caller asks `complete()` for the *next* assistant message; a history that
> already ends with one has nothing left to answer, and an empty history has
> nothing to answer at all. Either is a malformed request and raises
> `ModelError` before any model is contacted.

Stated on the roles of `messages`, deliberately — not on any translated
representation — so it binds an implementation that never touches pydantic-ai.
`Role.SYSTEM` is unaffected: a history ending in a system turn is a request and
stays one. `Role.TOOL` is out of scope here; it is not representable at this
layer at all and `PydanticAIProvider` already rejects it (issue #351 is not
about it).

### 2. Why refuse, rather than document the echo as defined behaviour

Documenting it is a legitimate option and it is the one we reject. Four reasons,
in the order of how much they weigh.

**A returned value carries no disposition, so nothing downstream can act on
it.** This is the decisive asymmetry. `ModelError` carries `retryable` and
`routable`, and the two wrappers consume them: `RetryingProvider` re-raises a
non-retryable failure "immediately, without consuming attempts", and
`RoutingProvider` re-raises a non-routable one without trying the next route
(ADR-0013 §5). A `Message` has no such surface. An echo does not merely fail to
be retried — it is indistinguishable from success, so a router counts its
primary as having *answered* and never considers a fallback at all. The failure
mode is not "a bad answer"; it is "a fabricated success that suppresses every
recovery path built above it".

**It is invisible in exactly the two places anyone would look.** An echo costs no
tokens, makes no HTTP request, and takes no measurable time. Spend graphs, request
counts and latency — the signals an operator would use to notice a model that
stopped being called — all read as normal, because from their point of view
nothing happened. A raise, by contrast, surfaces on the first call, at the seam,
in the caller's own stack.

**The echo is a fixed point, which is worse than a wrong answer.** Today's only
caller is one line from demonstrating it: if `ModelBackedPlanner.plan` appended
`reply` without the accompanying repair prompt, attempt two would be handed a
history ending in that reply, get it back verbatim, fail the same extraction the
same way, and exhaust `max_attempts` against a model it never called. A repair
loop that converges instantly on the output it was trying to repair is a
plausible bug for the *next* caller, and it is one whose symptom — "the model
keeps giving the same broken answer" — points the investigation at the model.

**No caller wants echo semantics.** The scenario that sounds like one — resuming
a conversation for display — has the trailing assistant message already in hand
and can read `messages[-1]`. Routing that through a model client is an identity
function with a network stack bolted to it, and it is not the question
`complete()` names.

### 3. `ModelError`, not `ConfigurationError`, and not a new subclass

`complete()` already raises a bare `ModelError` for its one other malformed
argument — `ModelError("complete() requires at least one message")`, neither
retryable nor routable, in both implementations. The answered history is the same
category of fault at the same seam and gets the same treatment.

**Why not `ConfigurationError`,** which the immediately preceding lane
(`ensure_vendor_available`, ADR-0062 §2) deliberately chose *over* `ModelError`
for a bad model spec. That choice does not transfer, and the reason it does not
is worth stating because the two look alike from a distance. The distinction is
not "would a retry help" — it would not, in either case. It is **whose mistake it
is and where it is fixed**. A missing vendor package is a property of the
deployment: fixed by an operator changing a setting, identical on every call for
the lifetime of the process, and correctly reported by an adapter's
`AssistantError` boundary as a startup misconfiguration. A message list is
per-call data built by calling code: fixed by a programmer at the call site, and
freely malformed on one call and well-formed on the next inside a perfectly
configured process. Reporting that as a configuration failure would send an
operator to the config file to fix a bug in a caller.

**Why not a new `ModelError` subclass.** A subclass buys a caller the ability to
distinguish this from other model failures, and there is nothing to do with the
distinction: the recovery is the same as for the empty list — fix the caller —
and the bare class's `retryable = False, routable = False` is already the right
disposition, since a malformed argument reproduces identically on every attempt
from every route. Adding a public type to `core/errors.py` to label a fault
nobody handles differently widens the contract surface for no consumer.

### 4. Prefill is reserved, not foreclosed

The one substantive argument for keeping a trailing assistant turn meaningful is
**assistant prefill** — handing a model a partial assistant turn and asking it to
continue. It is a real capability that some vendors offer, and a history ending
on an assistant turn is the natural way to express it.

It does not survive contact with three facts. It is **not what happens today**:
the model is never called, so nothing is being continued — prefill is not
supported by accident, it is absent. It is **not uniformly available across
vendors**, so promising it on a model-agnostic seam would put a vendor-specific
capability into the one contract ADR-0061 exists to keep vendor-independent. And
it is **not reachable through this code path** regardless: `Agent.run` resolves a
trailing-response history as a finished run rather than as a continuation
request, which is the defect itself.

So refusing costs prefill nothing it has. What refusing *buys* is that the input
shape stays unspent: if prefill is ever wanted it arrives as an explicit surface
— a flag, or a distinct method — with its own ADR, rather than as an overloaded
reading of a plain history whose other reading is a silent no-op. Blessing the
echo would spend that shape on the one behaviour nobody asked for.

### 5. The promise binds the Protocol, and is enforced in the shared suite

**The rule goes on `ModelProvider.complete` in `core/protocols.py`, not only on
`PydanticAIProvider`.** It is a precondition on an argument every caller passes
through the Protocol, and the implementations demonstrably disagree about it
today (Context). A docstring on `PydanticAIProvider` alone would leave the
canonical fake free to keep diverging, and would leave the divergence
unenforceable by the one suite both implementations run.

`RoutingProvider` and `RetryingProvider` are `ModelProvider`s too and satisfy the
rule by delegation without a line of new code: each forwards `messages`
unchanged, so a wrapped provider's refusal propagates as a non-retryable,
non-routable `ModelError`, which is precisely the fail-fast disposition each
wrapper already implements for that flag pair.

**On placement**, ADR-0060 §1 put its cancellation rule in the module docstring
because it bound thirteen Protocols; §2's "no filler clauses" is the same
judgement from the other side. That reasoning argues *against* module level here:
this is a precondition on one method's argument, meaningless to twelve of those
Protocols, and hoisting it would produce exactly the clause-that-says-nothing §2
warns about. It belongs on the method it constrains.

**Enforcement lands with the binding, unlike ADR-0060 §5's `ModelProvider`
deferral.** That deferral was about cancellation, which needs a fake modelling a
resource it does not own; this is a handful of offline assertions — pass
`[USER, ASSISTANT]`, expect a `ModelError` that is neither retryable nor
routable (§6) — each deterministic,
implementation-independent and needing no network. There is no reason to defer it,
so `CONTRIBUTING.md`'s "extend the suite in the same change, so the new
obligation is enforced rather than assumed" is satisfied outright.

**The empty-list rejection is promoted at the same time.** It is the same
precondition and belongs in the same sentence. Note the asymmetry honestly: for
the empty list this is **ratification of behaviour that already exists
identically in both implementations** — no production code changes, only the
suite gains a case and a standing note is retired — whereas the answered history
is a genuine behaviour change in `PydanticAIProvider`. Both are contract
widening and both are why this ADR exists; only one of them alters what any code
does.

### 6. What the implementation lane owes

1. **`core/protocols.py`** — the precondition on `ModelProvider.complete`'s
   `messages` argument, plus a `Raises: ModelError` clause. This is the
   contract-surface edit golden rule 5 gates behind this ADR.
2. **`models/provider.py`** — `PydanticAIProvider.complete` rejects a history
   ending on `Role.ASSISTANT` *before* reaching `Agent.run`, with a bare
   `ModelError`, alongside the existing empty check.
3. **`src/ai_assistant/testing/models.py`** — `FakeModelProvider` mirrors the
   refusal, as it already mirrors the empty and tool-role rejections and for the
   same stated reason.
4. **`tests/models/model_provider_contract.py`** — shared cases for both halves
   of the precondition **and one for the boundary the rule deliberately does not
   cross** (below), so every implementation is held to them; the standing NOTE
   about empty input is retired, and the per-implementation empty tests that
   describe themselves as "not a shared-contract requirement" are reconciled with
   the suite rather than left contradicting it.
5. **`tests/models/test_provider.py`** — a case pinning `PydanticAIProvider`'s
   refusal specifically, and one pinning that it refuses *before* `Agent.run`
   (below).

Test *design* is the lane's; four properties are not, because a suite missing
any of them certifies something this ADR decided against.

**The refusal must pin the failure's *disposition*, not merely its base class.**
`pytest.raises(ModelError)` is satisfied by `ModelUnavailableError`, which is
`retryable = True, routable = True` — so an implementation could pass the case
while `RetryingProvider` burned its whole attempt budget and `RoutingProvider`
walked the malformed conversation down every fallback route. That is precisely
the waste §2 and §3 rest on avoiding, so the assertion is on `retryable is False`
and `routable is False`. Deliberately the disposition rather than
`type(exc) is ModelError`: identity would forbid a future implementation from
raising a more specific subclass that behaves correctly, and the class was never
the property — the flag pair is.

**A history ending on `Role.SYSTEM` must be asserted to *succeed*.** §1 draws the
rule at the trailing assistant turn and not at "ends on `Role.USER`", on the
strength of a verified fact; but every positive case in the suite today ends on a
user turn, so an implementation that wrote the over-broad
`if messages[-1].role is not Role.USER: raise` would pass the refusal cases and
the existing conversation cases alike, while rejecting a call that works today. A
rule whose boundary nothing tests is a rule the next implementation gets to
redraw, so the suite pins both sides of it.

**The refusal must be asserted by the raise, not by an absent request.** "Zero
request bodies" is true of the fixed code and of the broken code alike — the
whole defect is that the broken code makes no request either — so a
recorder-based case would certify the bug it was written to catch. The
`vendor_stacks.py` recorder is the right tool for showing *what* went on the wire
and the wrong one for showing that something should have.

**The "before `Agent.run`" ordering in obligation 2 must itself be pinned, and it
is the one obligation that costs a reach into a private.** An implementation that
calls `Agent.run`, gets the echo back and *then* raises satisfies every assertion
above, because today's short-circuit means the reject-after ordering also issues
no request and never reaches the model — so neither the recorder nor a
`FunctionModel` spy can tell the two apart. The only instrument that can is a spy
on the provider's own `_agent.run`, asserting it was never invoked for a
trailing-assistant history. That belongs in `test_provider.py` and **not** in the
shared suite, which must not know that an implementation has an `_agent` at all;
it is acceptable there because the module already imports `_to_model_messages`
under a `reportPrivateUsage` suppression, and because the alternative — putting an
observability affordance on the production seam — is the trade ADR-0060 §5
refused. The ordering is worth pinning rather than trusting: it is what keeps the
refusal free of a vendor round trip if pydantic-ai ever stops short-circuiting.

The lane inherits a useful fact: with this refusal spiked into **both**
`PydanticAIProvider` and `FakeModelProvider`, the entire existing suite passes
unchanged (8540 passed, 2 skipped). No existing test depends on the echo, and no
existing history handed to `complete()` anywhere in the tree ends on an assistant
turn. The spike was discarded; this ADR ships alone.

### Rejected

- **Document the echo as defined behaviour.** §2. The option the issue names
  first, and the one that trades a loud failure for a fabricated success that no
  wrapper above the seam can see.
- **`ConfigurationError`, following ADR-0062 §2.** §3 — that precedent tracks
  where a fault is fixed, and it points the other way for per-call data.
- **A dedicated `ModelError` subclass.** §3 — public surface for a distinction
  no caller would act on.
- **Put the check in `_to_model_messages`.** It is private to one adapter and
  translates nothing for the fake, so the rule would bind neither implementation
  it needs to bind. The precondition belongs to `complete()`, which is where the
  contract is.
- **Append a synthetic user turn to force a real call.** Fabricating input the
  caller never wrote and sending it to a model is a larger surprise than either
  candidate, and it silently changes what was asked.

## Consequences

- **The seam stops being able to answer without asking.** A caller that hands
  `complete()` an already-answered conversation learns immediately, at the call,
  instead of receiving its own input back as an assistant message.
- **The two implementations agree, and the suite says so.** Today's divergence
  between `PydanticAIProvider` and `FakeModelProvider` on this input is closed by
  a case both must pass, which is the property `ai_assistant.testing` is for.
- **One input shape becomes an error rather than a behaviour**, which is a
  narrowing of what `complete()` accepts. Nothing in the tree relies on it —
  verified by spike — but a future caller wanting continuation semantics must ask
  for them explicitly, via a surface and an ADR that do not yet exist (§4).
- **The Protocol now states a precondition on `messages` at all**, where it
  previously stated none. That makes it the natural home for the next one; it
  also means an implementation may no longer treat any `Sequence[Message]` as
  acceptable input, which is a real obligation on a future third implementation.
- **Reopen this if prefill becomes a requirement.** The trigger is a concrete
  caller needing a model to continue a partial assistant turn, across vendors
  that all support it. That is a new capability with its own contract question,
  not an amendment to this one.
