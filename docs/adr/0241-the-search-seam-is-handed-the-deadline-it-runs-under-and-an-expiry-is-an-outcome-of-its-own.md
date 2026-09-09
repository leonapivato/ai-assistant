# 241. The search seam is handed the deadline it runs under, and an expiry is an outcome of its own

- Status: Accepted
- Date: 2026-09-09
- **Partially supersedes**
  [ADR-0231](0231-the-planner-asks-for-a-search-the-turns-own-words-compose-it-and-the-results-come-back-as-records.md)
  — **two scopes of §17, and nothing else in that ADR.** (i) The exact-signature
  declaration of one member: `async def search(self, call: ToolCall, /) -> SearchOutcome`
  gains **one keyword-only parameter**, `timeout: timedelta`. §17's three-member closure
  binds entire, `call` stays positional-only, `request`'s signature is untouched, and
  §17's clause that *"No member of this Protocol takes a `MemoryRecord`, a supply, a
  `MemoryStore`, an `ActionPolicy`, an `AuditTrail` or a `RecipientGrants`"* binds
  verbatim — a duration is none of the six and §1 below is written so that it can never
  become one. (ii) §17's closure of `SearchRefusal` at **exactly six members**, in that
  count alone: the six it names, their values, their lower-cased spellings, the
  added-to-and-never-renamed rule and the raises-for-no-source-reason posture all stand
  entire, and the enumeration becomes seven.
- **Partially supersedes**
  [ADR-0238](0238-a-destination-the-user-chose-may-be-told-what-the-turn-knows-and-the-searching-that-follows-runs-under-a-per-conversation-budget.md)
  — **two scopes, and nothing else in that ADR.** (i) §13's `core`-surface clause in one
  limb: *"`ActionPolicy`, `AuditTrail`, `MemoryStore` and `WebSearcher` each gain no
  member, no argument and no widened return"* — `WebSearcher` gains one argument, on one
  member, and the limb is moved **for `WebSearcher` alone**. `ActionPolicy`, `AuditTrail`
  and `MemoryStore` are untouched, `WebSearcher` gains no member and no widened return,
  and every other clause of §13 — the enumerated `core/types.py` additions, the
  `PROTOCOL_VERSION` move, `ConfirmationEgress`, `ConversationExport` and the two
  decodes-as-written clauses — binds entire. (ii) §11's closure of `SearchDisposition` at
  **exactly sixteen members**, in that count alone, including its *"no lane reads this as
  licence to add a seventeenth"* sentence: the enumeration becomes **eighteen**. Its
  members, their values, the injectivity of every mapping into it, its no-message rule
  and its exclusion of `SearchRefusal.NO_RESULT` all stand entire, and §11's audit
  clauses — one event, one key, counts only — bind verbatim.
- **Amends the same ADR** — **§8's no-per-call-bound premise, and that alone.** §8 states
  as its ground for deriving nothing that *"`WebSearcher.search(call, /)` takes **no
  timeout and no deadline**, ADR-0231 states none for that seam"*, and concludes *"With
  no bound on one servicing, no product of two ratified quantities bounds a
  conversation's."* §1 below supplies the missing bound, so the premise stops being true
  once this ADR's implementing lane lands. **Nothing §8 decided changes**: it bounds
  provider calls and not elapsed time; it adds no second `Settings` field, no stored
  elapsed counter, no provisional charge and no `SearchClaim` handle; its correction of
  the ADR-0228 §4 derivation stands, and §9 below neither reinstates the deleted
  apparatus nor states a per-conversation elapsed bound. This is ADR-0060's own header
  shape one seam over — ADR-0118 put a deadline on the embedding seam and **amended**
  ADR-0060 §5's assessment rather than superseding anything it decided — and §14 works
  the classification.
- **This is a contract change.** It adds a parameter to a member of
  `core/protocols.py`, a member to a `core/types.py` enumeration and a field to
  `core.config.Settings`. Golden rule 5 applies: this ADR ships as **its own PR,
  ratified ahead of any implementation** (ADR-0015 §5). It is reviewed while still
  `Proposed`, so a finding can still change the decision, and flipped to `Accepted` on
  merge. This PR is docs-only.
- Refs: #2167 (the milestone-31 obligation this answers), #2112 (ruled in §8), #2181
  (deferred in §13, filed by this lane), #1908 (milestone 31's live record), ADR-0029 §4,
  ADR-0060, ADR-0118, ADR-0192, ADR-0194, ADR-0226 §5, ADR-0228 §4 and §10, ADR-0231,
  ADR-0238.

## Context

### Where this comes from

The owner amended milestone 31 on `track:planning`'s live record (#1908) on 2026-09-09,
and #2167 is the obligation that amendment created. Its words are this ADR's brief:

> Search deadlines and cancellation; distinguish call allowance, monetary spend controls,
> and elapsed-time limits. **Decide how the deadline reaches the search contract.**

and its acceptance:

> A deliberately stalled search is terminated within the declared bound; cancellation
> leaves an accurate outcome and budget accounting; the user receives a useful result or
> an explicit interruption account.

ADR-0238 §16 deferred *"a per-conversation bound on elapsed search time"* and named the
trigger precisely: **"Fired by an ADR that first decides how a deadline reaches
`WebSearcher.search` at all — a `core/protocols.py` change, and so its own ratified ADR
under golden rule 5"**, and separately *"by the owner ruling that milestone 31's exit is
not met by calls and cost alone"*. Both triggers have fired. This ADR is the first half;
the per-conversation bound stays deferred and §13 restates what now fires it, because for
the first time it is a quantity that can be stated at all.

### The exit, and what this ADR can and cannot demonstrate

**This ADR decides a contract and lands no code**, under golden rule 5 and ADR-0015 §5.
Its implementing lane is separate and is briefed from the merged text.

**Its subject is live on the tree, unlike ADR-0238's.** ADR-0235's establishing surface
and ADR-0236's per-call figure both landed, so a search can reach an `ALLOW` and can
complete today. A deployment therefore already runs the 30-second bound §1 relocates, and
already records the two things §4 and §5 change. Nothing here is inert on merge, and §11
is written on that footing.

### The tree, read rather than assumed, at `origin/main` `2c8aebfc`

- **`WebSearcher` in `core/protocols.py`** declares three members —
  `name`, `async def request(self, query: NonBlankEncodableText, /) -> ActionRequest | None`
  and `async def search(self, call: ToolCall, /) -> SearchOutcome`. **Neither acting
  member takes a timeout or a deadline**, and the Protocol's own text says what it does
  say about being cut short: a call *"cancelled from outside while suspended re-raises
  `CancelledError` and is converted into neither an outcome nor a refusal"*.
- **`tools/web_search.py` holds the bound as a module constant.**
  `WEB_SEARCH_TIMEOUT: Final = timedelta(seconds=30)`, documented as *"ADR-0029 §4's
  invocation deadline for one search"* and deliberately **not** a `Settings` field, on
  the ground that ADR-0231 §5 *"adds exactly four fields and every one of them is a bound
  on a quantity, which a deadline is not"*. `WebSearchEgress.__init__` takes it as a
  defaulted `timeout` keyword and passes it through `checked_timeout`, which is ADR-0029
  §4's guard.
- **`app/composition.py` does not pass one.** `build_web_search_integration` is called
  with the connection, the origin, the two bounds and ADR-0236's cost pair, and with no
  `timeout`, so **the 30 seconds is not operator-configurable in any deployment**.
- **An expiry is indistinguishable from a broken channel.** In `search`,
  `except TimeoutError: outcome = _refused(SearchRefusal.TRANSPORT_FAILED)`; and where
  the deadline expires inside or immediately after the spend admission, the same class is
  returned from a second site (`if outcome is None:`). `SearchRefusal.TRANSPORT_FAILED`'s
  own docstring lists *"a refused connection, a TLS failure, a channel closed
  mid-response, an expired deadline"* as one member.
- **`tools/egress.py` sets no socket timeout**, by design: the invocation deadline is
  *"what bounds the call as a whole"*.
- **`admitted_call` and `consumed_call` already do the harder half correctly.**
  The admission and the callable share one window (`admitted_call`'s
  `expires_at = loop.time() + timeout.total_seconds()`, and `act` is handed what is left);
  a claim is completed on **every** exit the frame observes; and a cancellation from
  outside completes the claim with `definition.interrupted_outcome` and
  `unknown_cost()` before re-raising.
- **`ToolDefinition.interrupted_outcome` exists and is ADR-0029 §4's rule as a property**
  — `FAILED` where the tool is not `side_effecting` or its `idempotency` is `NATURAL`,
  `INDETERMINATE` otherwise — and its docstring names *"the seam on a deadline expiry"*
  as one of its three readers.
- **`WEB_SEARCH` is `side_effecting=True` with `idempotency=NONE`**, so its
  `interrupted_outcome` is `INDETERMINATE`.
- **The disposition vocabulary has no member for a fault at the send.**
  `orchestration/reads.py` catches an `AssistantError` out of the servicing, raises
  `_ServicingFailedError(type(exc).__name__) from None`, and degrades under ADR-0226 §5
  with the disposition left empty — the residue its own docstring names as issue #2112.
- **The conformance suite pins the signature.**
  `tests/tools/web_searcher_contract.py::test_each_acting_member_takes_exactly_one_positional_parameter`
  asserts that each acting member *"takes exactly one positional-only parameter and no
  keyword parameters (ADR-0231 §17)"*.
- **The canonical fake can be made to wait.** `FakeWebSearcher.suspend_next()` returns a
  `LoopSuspension`, which is the lever a suite needs to hold a search open on the event
  loop.

### Claims in the framing that do not survive contact with the tree

- **A `Settings` field would not move ADR-0231 §5's count.** §5's clause is *"**This
  decision** adds exactly four `Settings` fields"* — a statement about what ADR-0231
  adds, not a closure over `Settings`. A fifth field added by a later ADR makes no
  sentence of §5 false, so it is a **stacked addition** under ADR-0082 §1 and no record
  is owed on ADR-0231 §5. What is stale is the *module comment* in
  `tools/web_search.py` reasoning from that count to "not a `Settings` field"; §11 has
  the implementing lane rewrite it.
- **A fault at the send is not invisible today, and #2112 slightly understates the
  tree.** Besides the empty disposition, `orchestration/reads.py` emits a separate
  `read_request_degraded` WARNING carrying `refused_by=<class name>`. What is missing is
  not a signal but a **countable** one: the `turn_read_request` event, which is the
  instrument ADR-0231 §13 and ADR-0226 §8 make population reads from, has no member for
  it. §8 rules on that gap and leaves the WARNING exactly where it is.
- **`TRANSPORT_FAILED` is worse than ambiguous — it forces a false ledger row.** The two
  conditions it collapses differ in what they let the system assert: a refused connection
  provably disclosed nothing, and an expiry may have disclosed everything. Because
  `_result_of` maps the one member to `ToolOutcome.FAILED`, an expired search's
  completion row today says *the call did not act* about a `side_effecting`,
  non-`NATURAL` tool — the one direction ADR-0014 §4 refuses to guess in and the one
  `ToolDefinition.interrupted_outcome` exists to prevent. §5 corrects it, and this is the
  strongest argument for a separate member rather than a nicer audit label.
- **ADR-0029 §4's clauses do not have to move.** They are stated over
  `ToolInvoker.invoke`, and ADR-0231 §5 already applies §4's deadline at this second
  route by reference (*"ADR-0029 §4's invocation deadline bounds the call, and it is not
  one of the three"*). Adopting its **shape** at a seam that is not `invoke` contradicts
  no sentence of §4 — in particular not its *"`ToolDefinition` does not gain a timeout
  field"*, which §1 below relies on rather than moves.

### What this ADR is not allowed to settle

- **A per-conversation bound on elapsed search time.** ADR-0238 §8 deletes the apparatus
  and §16 defers the bound; this ADR supplies the missing quantity and stops there (§9,
  §13).
- **A per-operation figure for the bound.** ADR-0228 §4 fixes planning budgets per
  operation; §3 below deliberately ships one deployment-wide figure and §13 defers the
  per-operation one with its trigger.
- **How a reply renders an interruption.** §10 states the fact that crosses; the wording,
  the surface and the rendering are the sibling contract ADR's — the one #2168's lane is
  writing beside this one — and
  ADR-0231 §19's *"Telling the user that a search was refused"* deferral is that lane's
  and is not fired here.
- **Anything about the call ceiling or the monetary ceiling.** ADR-0238 §8's figure,
  ADR-0194 §8's deferred default (#2116) and ADR-0236's per-call figure are each left
  exactly where they stand (§9).
- **The transport's internals.** No socket timeout, connect timeout or read timeout is
  decided here; §2's second clause says why.

## Decision

### 1. The bound is the caller's, and it reaches the seam as a required keyword on `search`

> **Normative.** `WebSearcher.search` gains **one keyword-only parameter**,
> `timeout: timedelta`, **required and with no default**, so its declaration becomes
> `async def search(self, call: ToolCall, /, *, timeout: timedelta) -> SearchOutcome`.
> `call` stays positional-only, `request` is untouched, and the Protocol gains **no
> member and no widened return**. This is the whole of the `core/protocols.py` change.

> **Normative.** **There is no spelling for "unbounded".** The parameter has no default,
> admits no `None`, and every call declares a bound. That is ADR-0029 §4's rule at this
> seam verbatim — *"a required keyword-only argument with no default, so the contract has
> no spelling for 'forever'"* — and its reasoning transfers unchanged: a default would be
> `core` choosing a policy, and a nullable one would be a documented route to an
> unbounded call.

> **Normative.** **The annotation is not the enforcement, so the implementation checks
> the value.** A `timeout` that is not a `timedelta`, or is not strictly positive, is
> refused with `ValueError` **before** the call is revalidated, before the credential is
> read, before the spend gate is consulted and before any channel is opened — so a
> refused value reaches no store, appends no claim and opens nothing. Zero and negative
> durations are refused rather than treated as instantly expired, for ADR-0029 §4's own
> reason: expiry is delivered at an await point, so an implementation reading "expired"
> as "do not call" would be making a promise the event loop does not keep.

> **Normative.** **The bound covers this seam's own work and not the send alone** — the
> revalidation, ADR-0194 §3's spend admission, the credential read, the channel, the
> response read and the transcription. A bound over the send alone is a bound with a hole
> exactly where a gate can stop answering, which is ADR-0118 §4's second clause one seam
> over, and §3's admission clause already places that stage inside the deadline.

> **Normative.** **It is not placed over either ledger append, and this ADR does not move
> that.** ADR-0192 §3 pins the claim and the completion as *"unbounded by this seam"* and
> gives the reason a bound there would be a fiction — the audit store this corpus ships
> absorbs a cancellation until its worker physically finishes (ADR-0054), so cancelling
> the append returns nobody sooner — and §7 of that ADR already records the consequence
> against ADR-0029 §4 over both windows. **No lane closes that gap by wrapping either
> append in this ADR's deadline**; each stays a retained, shielded await.

> **Normative.** **The guarantee is therefore stated in the weaker, true form, and this
> ADR claims no total for a `search` frame.** What the bound buys is that the seam stops
> waiting on the stages it owns; it does not stop a provider working, does not interrupt
> a callable that declines to be cancelled, and does not bound a store that has stopped
> answering. ADR-0192's *"This ADR claims **no** total for `invoke`'s frame either"* is
> the same sentence one seam over, and a reader who takes §1 for a wall-clock ceiling on
> `search` has read it too strongly.

> **Normative.** **The parameter is a duration and nothing else, and no lane widens it.**
> It is not a deadline instant, not a clock, not a budget object, not a policy and not a
> carrier for a second value. ADR-0231 §17's clause that no member of this Protocol takes
> a `MemoryRecord`, a supply, a `MemoryStore`, an `ActionPolicy`, an `AuditTrail` or a
> `RecipientGrants` binds verbatim, and this parameter is the one addition to that
> signature any ADR has made; a later lane widening it into a type carrying anything a
> store, a supply or a model produced is making the change §17 forbids.

**The bound is the caller's budget, not the searcher's property, and that is why it is a
parameter.** ADR-0029 §4 settled the identical question for `invoke` and its sentence is
the whole argument here: *"How long a turn may wait is a property of the turn: an
interactive request and a background one are entitled to different answers about the same
tool."* A conversational turn, a spoken turn and a future worn-earpiece turn tolerate very
different waits over one connected account, and ADR-0228 §4 has already ruled that shape
for the planner — *"Keyed on the operation because two operations of one audience have
different latency tolerances."* A bound fixed inside the searcher, or wired once at
composition, makes the per-operation figure unstateable; a parameter makes it a later
`Settings` or per-operation decision rather than a later Protocol change. §3 ships one
figure today and §13 defers the second; what §1 buys is that deferring it costs nothing.

**And a caller may now assume something it could not assume before, which is what makes
this golden rule 5's business rather than an implementation detail.** ADR-0118 §9 states
the test — *"whether a caller of `Embedder` must now assume something it could not assume
before"* — and answered no. Here it comes out yes in both directions. A caller must now
**supply** a bound, and may now **assume** that the seam stops waiting on the stages it
owns and that an expiry comes back as a classified `SearchOutcome` rather than as a hang
or an exception. That is the guarantee in §1's weaker, true form and not a finite total
for the frame — a stalled ledger append still blocks, by ADR-0192 §3's own trade. Neither
half is derivable from ADR-0231's text, and a contract whose callers must read a
composition root to learn whether the seam bounds anything at all is not stating what it
promises.

### 2. Why the seam and not a decorator, when ADR-0118 chose the decorator

> **Normative.** **The deadline is enforced inside the implementation of `search`**, and
> not by a wrapping `WebSearcher` the composition root interposes. No lane satisfies this
> ADR with a decorating searcher that bounds an inner one, and no lane satisfies it by
> having a caller wrap `search` in `asyncio.timeout` or `asyncio.wait_for`.

> **Normative.** **No socket, connect or read timeout is decided here.** `tools/egress.py`
> keeps the posture ADR-0231 §5 gave it — the invocation deadline is what bounds the call
> as a whole — and a lane that adds a transport-level bound is deciding something this
> ADR does not.

**ADR-0118 refused four placements for the embedding deadline and chose a fifth, and its
reasoning is checked here rather than inherited.** It put the bound in a decorating
`Embedder` because the bound there is *"a ceiling on pathology"*, one figure for every
caller of a seam whose callers have no opinion, and because §9's caller test came out no.
Two facts make the same shape wrong here.

**First, a decorator cannot classify the expiry without breaking the clause this seam
already carries.** An outer `asyncio.timeout` cancels the inner call, and ADR-0231 §17
and `core/protocols.py`'s own text require a `search` cancelled while suspended to
re-raise and to be *"converted into neither an outcome nor a refusal"*. So the inner
searcher must re-raise; the decorator must then convert a cancellation it caused into a
refusal, which is the conversion the Protocol forbids performed one frame out, by an
object whose only evidence about provenance is an exception type. ADR-0029 §4 already
ruled that route out in terms — *"A caller wrapping `invoke` in `asyncio.wait_for` cancels
the invoker mid-await, so the invoker never reaches the code that classifies the outcome …
Enforcing inside means the expiry comes back as a classified `ToolResult`"* — and adds the
ground that no exception type is evidence of where a cancellation came from. Only the
frame that set the deadline knows it expired.

**Second, the accounting is inside.** ADR-0192's claim is appended immediately before the
callable and completed on every exit; ADR-0194 §3's admission shares the same window. A
decorator standing outside `search` stands outside both, so an expiry it produced would be
reported by an object that cannot write the completion row §5 requires, and the window
`admitted_call` already makes one would silently become two.

**What ADR-0118 §2 was actually refusing is untouched.** It refused a deadline *inside one
adapter* because that binds one implementation and re-opens the hole for the next one. §1
is the opposite arrangement: the obligation is on **the contract**, so every `WebSearcher`
this system ever wires is bounded on the day it is written, and the canonical fake is
bounded too.

### 3. `Settings` gains one field, the module constant goes, and the servicing site passes it

> **Normative.** `core.config.Settings` gains exactly **one** field,
> **`search_call_deadline: timedelta`**, defaulting to **30 seconds**, and finite and
> **strictly positive**. A value outside that domain is refused at `Settings` load with
> the `ConfigurationError` ADR-0194 §1's configured-amount clause requires, naming the
> field. It is the `_DurationSetting` shape `calendar_read_timeout` already carries.

> **Normative.** **The bound ships with a value rather than meaning "unbounded" when
> unset.** ADR-0194 §1's *"unset means unbounded"* governs a monetary ceiling an operator
> chooses; a bound the milestone's exit is stated over may not be absent by omission, and
> §1 gives the contract no spelling for absent anyway. A deployment that configures
> nothing still searches under this figure.

> **Normative.** **Thirty seconds, unchanged, and it is the figure the tree already
> runs.** This decision relocates a bound and reclassifies its expiry; it does not
> retune. A lane that wants a different default is moving a number an operator can
> already move.

> **Normative.** **`WEB_SEARCH_TIMEOUT` and `WebSearchEgress.__init__`'s `timeout`
> parameter are both deleted.** The bound comes from one place — the value the caller
> passes — and a searcher holding a second one would be a searcher able to disagree with
> its caller about what window it is running in.

> **Normative.** **`orchestration` reads the field and passes it at the call.** The
> composition root hands the value to the servicing site that holds the `WebSearcher`
> (`app/composition.py`, `CLAUDE.md`'s *"the only place concretes are wired"*), and that
> site passes it as `timeout` on every `search`. No component below `orchestration` reads
> the setting, and no component above the servicing site holds a duration on account of
> this decision.

**The shape is ADR-0238 §12's, deliberately.** That clause makes the call ceiling *"a
`Settings` value read by `orchestration`"* so that nothing a model produced, a request
carried or a result contained can reach the comparison. The same construction gives the
deadline the same property for free, and §9 states it as an obligation rather than leaving
it to be inferred.

**A `Settings` field rather than a constant, because a constant an operator cannot reach
is a bound nobody can size.** The current arrangement has a figure argued in a module
comment, a constructor parameter no composition root passes, and no route from a
deployment to either. A provider whose tail latency does not fit thirty seconds is today a
code change.

### 4. An expiry is its own refusal, and its own disposition

> **Normative.** `core/types.py`'s `SearchRefusal` gains **exactly one** member,
> **`DEADLINE_EXPIRED`**, valued `deadline_expired`: **the bound §1 handed this call
> expired before the search produced an answer.** The enumeration is closed at **seven**,
> the vocabulary is added to and never renamed, and no later lane adds an eighth without
> the ADR that decides it.

> **Normative.** **It is returned and never raised**, exactly as the other six are. §1's
> `ValueError` guard is about a `timeout` an implementation could not run under and is
> refused before anything is read; an expiry of a valid bound is an outcome, so ADR-0231
> §17's raises-for-no-source-reason posture binds unchanged and `core/errors.py` gains no
> class.

> **Normative.** **`SearchRefusal.TRANSPORT_FAILED` stops covering an expiry of this
> seam's own deadline, and that is the whole of what moves.** Its other conditions — a
> refused connection, a TLS failure, a channel closed mid-response, a refused redirect —
> keep the member, keep the meaning ADR-0231 §5 and ADR-0191 §1 gave them and keep the
> `ToolOutcome` a completion records for them today. No implementation returns
> `TRANSPORT_FAILED` for a deadline, and no lane collapses the two back together.

> **Normative.** **This ADR asserts nothing about whether any of those conditions
> disclosed anything.** A channel closed mid-response may well have carried the whole
> query, and a refused redirect certainly did; whether their completion row is honest is
> a question about a member this ADR is not otherwise moving, and §13 records it as its
> own defect rather than answering it here. **No lane cites §4 as having established that
> a `TRANSPORT_FAILED` search disclosed nothing.**

> **Normative.** `SearchDisposition` gains **`DEADLINE_EXPIRED`**, valued
> `deadline_expired`, carried across from the refusal one for one, so the mapping from
> `SearchRefusal` into it stays **injective** and ADR-0231 §13's injectivity clause binds
> unchanged. It carries **no duration, no bound, no elapsed figure, no query, no origin
> and no message** — ADR-0231 §13's Tier 1 clause and ADR-0004 §5 bind without
> qualification, and a duration in a per-turn event is a fact about the system that
> ADR-0228 §10 has already refused to render.

**The audit reason and the ledger reason point the same way, and only the second is
decisive.** An operator reading a population of `turn_read_request` events cannot act on
"transport failure" if it means both "the provider is unreachable" and "the provider is
slow": the first is an outage, the second is a bound to size or a provider to change.
That is ADR-0231 §13's own standard — *"Collapsing them would make the one field useless
at exactly the moment someone reads it."* But the argument that would hold even with no
audit at all is §5's, and it is narrower than an appeal to disclosure: **ADR-0029 §4's
`FAILED`-or-`INDETERMINATE` rule attaches to a deadline expiry or a cancellation and to
nothing else**, and the seam is the only party that can establish that its own deadline
expired. While one member carries both an expiry and a refused connection, no mapping
from it can apply §4's rule to the first without applying it to the second, which §4 does
not reach. The split is what makes the classification computable at all.

### 5. The completion row on an expiry says `INDETERMINATE`, and today it says `FAILED`

> **Normative.** **Where the deadline expires after the ledger claim was appended, the
> completion carries `definition.interrupted_outcome`** — `INDETERMINATE` for
> `WEB_SEARCH`, which is `side_effecting` with `idempotency` `NONE` — **and an
> `UNKNOWN` incurred cost.** No implementation records `SUCCEEDED` for an expiry, and
> none records `FAILED` for one on a tool whose `interrupted_outcome` is
> `INDETERMINATE`.

> **Normative.** **`interrupted_outcome` is read from the searcher's own registered
> declaration** — the authoritative original ADR-0029 §2 puts where a registry's would be
> for this integration, and equivalently the revalidated detached copy — and never from
> `call.request.tool`. That is ADR-0029 §4's clause verbatim, and its reason transfers:
> the binding checks all ran before the callable started, so a declaration mutated
> mid-flight is re-examined by nothing.

> **Normative.** **Where the deadline expires before a claim was appended** — inside the
> spend admission, or between it and the claim — **no completion row is written, because
> there is no claim to complete.** ADR-0192 §1's placement is relied upon and not moved:
> before the claim there is no invocation row, and inventing one for a call that provably
> never ran would be the opposite error to the one this section corrects.

> **Normative.** **An expiry costs a period exactly what a completion costs it.** The
> completion's `incurred_cost` is `unknown_cost()`, so ADR-0194 §2 makes the period's
> accounted total indeterminate on the same terms ADR-0238 §10 already ratified for a
> successful search, and `world_spend_unknown_allowance` is the mechanism, used as
> designed. **No lane substitutes `web_search_cost_per_call` for the unknown figure** —
> ADR-0194 §2's estimate/reported boundary binds — and no lane treats an expiry as
> costing nothing on the ground that no answer came back.

**This corrects a live defect rather than adding behaviour, and the correction is the
whole reason §4's member is a member and not a label.** `_result_of` maps every refusal
other than `NO_RESULT` and `UNATTESTED` to `ToolOutcome.FAILED`, and an expiry arrives
there as `TRANSPORT_FAILED`. So a search whose query may have left the machine and may
have been served and billed is recorded as one that certainly did not act — about a tool
declared `side_effecting=True` with `idempotency=NONE` precisely so that this guess is
unavailable. ADR-0014 §4 refuses that guess in terms, ADR-0029 §4 restates it for a
deadline, and `ToolDefinition.interrupted_outcome` was written to compute the answer;
`consumed_call` already reads it on the cancellation path. The asymmetry is the bug: a
cancellation from outside completes `INDETERMINATE` and an expired deadline completes
`FAILED`, for the same call, over the same ignorance — and §4's split is what makes the
two agree, because ADR-0029 §4's rule can only be applied to a condition the seam can
establish is an expiry. What a `TRANSPORT_FAILED` completion should record for its
remaining conditions is a separate question this ADR leaves exactly where it found it
(§4, §13).

### 6. The call is spent, and nothing is refunded

> **Normative.** **An interrupted search spends the call ADR-0238 §8's `admit_search`
> admitted, and no path lowers `calls`.** ADR-0238 §15's Arm 6d — *"an admitted call is
> never refunded"* — binds a deadline expiry, a cancellation from outside and a fault at
> the send exactly as it binds a refused ruling and a provider refusal. No implementation
> decrements, re-credits, re-admits or re-runs on account of an expiry.

> **Normative.** **A conversation's `closed_loop` footing is unaffected by an
> interruption.** ADR-0238 §8's `observe_search` fold and §5's conditions are computed
> exactly as ratified; an expired search returns no record, so it contributes nothing to
> a supply and changes neither half of §5's third condition.

> **Normative.** **A `SearchRefusal.DEADLINE_EXPIRED` is a disposition and never a
> retry.** ADR-0231 §15's clause for the spend refusal is the shape and the reason is
> stronger here: a retry would spend a second admitted call against the same conversation
> budget on the same stalled provider, and ADR-0118 §3's *"each retry against a wedged
> backend abandons another worker"* is the same failure with a different resource's name
> on it.

**Refunding would be the one route by which a stalling provider could reach the budget.**
ADR-0238 §12 rules that *"A provider that stalls therefore cannot reach the budget at all
— it delays its own conversation and spends no extra call, which is what a counter of
calls buys that a counter of time did not."* A refund on expiry would hand a provider the
ability to make its own stalls free, so that clause is honoured here rather than merely
cited.

### 7. Cancellation from outside is unchanged, and this section demonstrates rather than rebuilds

> **Normative.** **A `search` cancelled from outside while suspended re-raises
> `CancelledError` and is converted into neither an outcome nor a refusal.** ADR-0060 §1
> and ADR-0231 §17 bind entire; this ADR adds no clause to either, and
> `SearchRefusal.DEADLINE_EXPIRED` is **never** returned for a cancellation the seam did
> not itself issue.

> **Normative.** **Classification keys on whether *this* deadline expired, and never on
> catching an exception type.** ADR-0029 §4's two clauses bind at this seam: a
> `TimeoutError` an upstream library raises for its own reasons is not this seam's expiry,
> and a `CancelledError` an inner callable invents when nothing was cancelled is a fault
> and not a teardown. The seam is the only party that knows the difference, and it
> establishes it from **its own deadline having fired and its own task having been
> cancelled** rather than from what was caught.

> **Normative.** **So the two misclassifications are named, each with the answer.** An
> upstream `TimeoutError` raised inside the bound is the transport's own failure and
> returns `SearchRefusal.TRANSPORT_FAILED`, exactly as it does today — **never**
> `DEADLINE_EXPIRED`. A `CancelledError` raised where no cancellation was requested is a
> fault the searcher raised, so it reaches ADR-0226 §5's degradation and §8's
> `SEARCH_FAILED` — **never** a teardown that ends the turn, and never an outcome. That
> is ADR-0029 §4's *"a tool that raised"* limb at this seam; which mechanism establishes
> the provenance is the implementing lane's, and that one must exist is this clause's.

> **Normative.** **A cancellation still completes the claim before it re-raises**, with
> `interrupted_outcome` and an `UNKNOWN` cost, and releases the channel — which is what
> `consumed_call` already does and what ADR-0192 §3 requires. §5's completion clause and
> this one are one rule read at two exits, not two rules.

> **Normative.** **The deadline stops the waiting, not the work.** No implementation
> represents an expiry as the request having been abandoned, and no caller assumes the
> query did not leave. That is ADR-0029 §4's cooperative limit, ADR-0060 §1's third clause
> and ADR-0118 §7's first clause, restated where this seam will be read, and it is the
> premise §5's `INDETERMINATE` rests on.

**The acceptance requirement asks for "an accurate outcome and budget accounting" under
cancellation, and the tree already supplies both.** What was missing is that nothing said
so at the contract, so a second `WebSearcher` could have satisfied every stated clause and
got it wrong. §7 states it; the implementing lane owes the arms in §12 that show it.

### 8. #2112 ruled: a fault at the send gets one disposition member, and nothing more

> **Normative.** `SearchDisposition` gains **`SEARCH_FAILED`**, valued `search_failed`:
> **the searcher itself raised a fault after the ruling** — a connection record it could
> not read, a ledger claim the trail refused, an authorisation already spent, or any
> other `AssistantError` escaping `WebSearcher.search`. It is **one member and not a
> family**: it carries no message, no exception type and no store detail, on
> `BINDING_FAILED`'s own rule, so there is nowhere in a Tier 2 event for one to sit
> (ADR-0231 §13, ADR-0004 §5).

> **Normative.** **`SearchDisposition` is therefore closed at eighteen**, counting
> ADR-0238 §11's sixteenth: these two and no others. Its members, their values, the
> injectivity of every mapping into it, its no-message rule and its exclusion of
> `SearchRefusal.NO_RESULT` all stand, and no lane reads this as licence to add a
> nineteenth.

> **Normative.** **`SEARCH_FAILED` is a `SearchDisposition` member and not a
> `SearchRefusal` one.** `SearchRefusal` crosses the `WebSearcher` seam and every member
> of it is a value `search` *returns*; these faults are raises, and converting them into
> returns would give the seam a value for conditions its caller must be free to see as
> exceptions. The asymmetry is stated because it is the one place the two vocabularies
> deliberately do not correspond.

> **Normative.** **ADR-0226 §5's degradation is unchanged and this member is not a
> second mechanism.** The servicing still fails all-or-nothing, the supply is left as
> planning saw it, every count is zero, `failed` is true, and nothing raises out of the
> turn. The disposition rides on the failing record, which ADR-0230 §9 and ADR-0231 §13
> already permit. The `read_request_degraded` WARNING and its `refused_by` class name are
> left exactly as they are: it answers the per-occurrence question and this member answers
> the population one.

**One member rather than the pair #2112 also offered, because the vocabulary's rule is one
member per stage.** `SearchDisposition`'s stated design is that *"Each member names the
stage that produced it … so no stage's outcome is reported as another stage's and none is
omitted"*, and `BINDING_FAILED` already covers *"refused or raised, or the connection
could not be read"* for one stage without splitting. Splitting the send's faults into a
store one and an authorisation one would put an exception taxonomy into a field §13 forbids
an exception type in, and would grow every time a new fault class reached the seam.

**And ruling it here rather than in the implementing lane is deliberate.** #2112 asks for
*"a ratified decision, either way"*, the two candidate answers are a vocabulary change and
a clause about an absence, and this is the ADR that already moves that vocabulary. Ruling
it in the same act costs one member and avoids a second contract round.

### 9. Three bounds, three names, and no cross-talk

> **Normative.** **This system bounds three different quantities on a search, and they
> are distinct in name, in mechanism and in the value an audit records.**
> **(a) Call allowance** — ADR-0238 §8's `search_calls_per_conversation`, a count of
> provider calls per conversation, enforced by `admit_search` before a query is composed,
> reported by ADR-0238 §11's member. **(b) Monetary spend** — ADR-0194's ceilings over
> ADR-0236's declared per-call figure, enforced by the `SpendGate` after ADR-0231 §6's
> three checks and before the ledger claim, reported as `SPEND_REFUSED`.
> **(c) Elapsed time** — §1's per-call deadline, enforced inside `search`, reported as
> §4's `DEADLINE_EXPIRED`. No implementation collapses any two, derives one from another,
> or reports one under another's member.

> **Normative.** **Each mechanism keeps exactly the inputs its own ADR gives it, and
> this ADR takes none of them away.** The call comparison reads a durable counter and a
> `Settings` integer (ADR-0238 §8, §12). The spend admission reads the pinned declaration,
> the configured amounts, the ledger's rows and reservations, and **the injected clock
> and `Settings.timezone` that select a calendar period** (ADR-0194 §1, §3) — every one of
> which is ratified and none of which is forbidden here. The deadline reads the duration
> §3's field carries and the event loop's own time.

> **Normative.** **What no mechanism reads is another's quantity.** No elapsed measurement
> of a search, and no figure derived from one, reaches the call comparison or the spend
> admission; no conversation draw reaches the spend admission or the deadline; and no
> configured or declared amount reaches the deadline. ADR-0238 §12's *"The comparison has
> no other input — no clock reading, no interval and no duration a provider could
> stretch"* binds verbatim **over the call comparison it was written about**, and this
> ADR's deadline is a **separate** comparison rather than a second input to it.

> **Normative.** **No value a model produced, and no value a search result carried,
> reaches any side of any of the three.** ADR-0238 §12's fuller prohibition — no value
> *"produced by a model, carried in a request, contained in a search result, or read from
> any record"* — binds verbatim **over the call comparison it was written about**, and
> this ADR states the same for the deadline: the duration is §3's `Settings` value read by
> `orchestration` and passed at the call, and no component raises, extends, resets,
> suspends or re-reads it on account of a turn's content. A deployment changes it in
> `Settings` and by no other route.

> **Normative.** **The spend admission keeps its own ratified inputs, and no clause here
> narrows them.** It reads the `ToolCost` on the revalidated, detached copy of the
> request — checked equal to the searcher's own registered declaration before it is read
> (ADR-0029 §2, ADR-0194 §3, §11) — and the ledger's recorded rows and reservations. Those
> are values a request carried and values records hold, they are what ADR-0194 §2 and §3
> require, and the clause above is stated so that it cannot be read as forbidding them.

> **Normative.** **A per-conversation bound on elapsed search time is not decided here.**
> ADR-0238 §8's deletion of the elapsed counter, the provisional charge and the
> `SearchClaim` handle stands entire; nothing in this ADR reinstates any of them, and §13
> restates the deferral with the trigger that is now stateable.

**Naming them apart is the requirement, not a nicety.** #2167 asks in terms to
*"distinguish call allowance, monetary spend controls, and elapsed-time limits"*, and the
tree's one live confusion is (c) wearing (a)'s and (b)'s clothes in the audit while a
fourth condition — a broken channel — wears (c)'s. §4 separates the last pair; this section
fixes the vocabulary so a later lane cannot re-merge them by convenience.

### 10. The interruption crosses to the composing stage as a bare fact, and #2168's ADR renders it

> **Normative.** **On a turn whose search was cut short by §1's deadline, the composing
> stage is given the bare fact that a search this turn was interrupted before it
> answered**, so that the reply can state it. On every other turn it is given nothing on
> this account, and the assembled prompt is byte-identical to what it is today.

> **Normative.** **The fact carries no duration, no bound, no count, no query, no origin,
> no provider name and no guard name.** It does not say how long the turn waited, what the
> bound was, or how many searches it made. ADR-0228 §10's clause and ADR-0226 §9's
> counts-and-no-copy reasoning bind this fact for their own reasons: nothing bounds what a
> planner puts in a query, and the turn's timing is a fact about the system rather than
> about the user's question.

> **Normative.** **It is carried inside `ai_assistant.orchestration`, from the component
> that knows it to the render site, as data.** It adds **no field to a `core` type**, no
> member to any Protocol, and it is never inferred at the render site — not from the plan,
> not from the supply's length, not from the audit. That is ADR-0227 §3's rule and
> ADR-0228 §10's third clause, applied to a third fact.

> **Normative.** **This ADR states the fact and not its rendering.** The wording, the
> surface and whether this fact travels on ADR-0228 §10's existing carrier or a sibling of
> it are decided by **the contract ADR #2168's lane is writing beside this one**, together
> with the explanations for a search that was refused or exhausted, so that one ADR owns how
> a turn accounts for a search it did not complete. It is named here by its obligation and
> not by number: its number is assigned at dispatch and its file is not in this corpus yet,
> and ADR-0088 §6's Tier 1 makes a citation of an ADR that does not exist a defect. **No lane implements two
> carriers for these facts.** Where that ADR has not landed when this one's implementing
> lane runs, the lane carries the fact in ADR-0228 §10's shape and the rendering ADR
> supersedes nothing by choosing otherwise.

> **Normative.** **No lane renders this fact through the step account.** ADR-0170 §5a's
> closed vocabularies are unchanged and gain no member.

**"A useful result or an explicit interruption account" is the acceptance sentence, and
the two halves have different owners.** A turn that stalls on its second search still
answers from what its first returned — the supply is monotone (ADR-0228 §7) and an expired
search returns no record rather than discarding one — so the *useful result* half is
already the corpus's behaviour and §12's fourth arm pins it. The *account* half needs a
fact to rest on, and ADR-0228 §10 has already argued why the fact must be given rather
than inferred: *"A turn that hits the bound has a plan, a supply wider than the one that
plan was made over, and an answer composed from all of it. The user's experience is a good
answer; what is missing is invisible."*

**One fact and not two, for §10's own reason.** A reply that named the deadline would
invite a retry into the same bound over the same provider; a reply that named the bound
would be telling the user about the system's configuration. Which guard fired is an
operator's question and §4's disposition answers it.

### 11. What the implementing lane owes

> **Normative.** **One lane, briefed from this ADR's merged text, and none before it is
> `Accepted` and merged** (golden rule 5).

It owes, and nothing beyond it:

- **`core/protocols.py`** — §1's parameter on `WebSearcher.search`, with the contract text
  it needs: that the bound is required and declared, that a non-`timedelta` or
  non-positive value raises `ValueError` before anything is read, that an expiry returns
  `SearchRefusal.DEADLINE_EXPIRED`, that the bound reaches this seam's own work and **not**
  the two ledger appends (§1, ADR-0192 §3), and that a cancellation from outside is
  unchanged (§7).
- **`core/types.py`** — §4's `SearchRefusal.DEADLINE_EXPIRED`, and the narrowing of
  `TRANSPORT_FAILED`'s stated scope so its docstring no longer names an expired deadline.
- **`core/config.py`** — §3's `search_call_deadline`, with its named default, its stated
  domain and its load-time refusal.
- **`orchestration/reads.py`** — §4's and §8's two `SearchDisposition` members, the
  mapping arm for the new refusal, and the site that passes `timeout` on every `search`.
- **`tools/web_search.py`** — the deleted constant and constructor parameter (§3), the two
  expiry sites returning the new member (§4), `_result_of` reading
  `interrupted_outcome` for it (§5), and the stale module comment reasoning from
  ADR-0231 §5's field count.
- **`app/composition.py`** — reading the field and handing it to the servicing site.
- **`tests/tools/web_searcher_contract.py`** — the shared conformance suite's new arms
  (§12), including narrowing its signature case, which today asserts that **each** acting
  member takes *"no keyword parameters"*, to `request` alone while keeping the
  one-positional-only-value-parameter half for both.
- **`ai_assistant.testing`'s `FakeWebSearcher`** — the parameter, the `ValueError` guard
  and honouring the bound over a call held open by `suspend_next`, so the suite's deadline
  arm runs against the canonical fake rather than being skipped.

> **Normative.** **`PROTOCOL_VERSION` does not move.** Nothing this ADR adds crosses the
> wire: `SearchRefusal` and `SearchDisposition` appear in no type any `AssistantEngine`
> member returns, `SearchOutcome` crosses one in-process seam, and neither
> `PermissionDecision` nor `EgressBinding` gains a field. ADR-0178 §6's rule is checked
> and comes out no. **A lane that finds this statement false moves the version in the same
> change** rather than reading this clause as permission not to.

> **Normative.** **No stored value changes, and nothing is back-filled.** No completion
> row, permission decision, conversation record or export written before this decision is
> re-read, re-classified or re-written; §5 governs rows written after it and no others.
> `ConversationExport.schema_version` stays at 2.

> **Normative.** **The lane changes no default and retunes nothing.** Thirty seconds
> (§3), `search_calls_per_conversation` (ADR-0238 §8), ADR-0231 §5's four bounds and
> ADR-0194's amounts are each left where they stand.

### 12. The representative-input tests this decision owes

> **Normative.** Each arm below is a test the implementing lane owes, over the production
> servicing path, the production searcher and the production `Settings`, and not over a
> double standing in for one of them. Arms 1 to 5 are milestone 31's pre-registered L1
> scenarios (#2178) and are named as such.

> **Normative.** **Arm 1 — the pre-registered stalled search.** A stub origin that
> connects and never answers, with `search_call_deadline` at 5 seconds and a ledger that
> answers promptly: the search completes within that bound plus a stated slack, the
> outcome's refusal is `DEADLINE_EXPIRED` and **not** `TRANSPORT_FAILED`, the audit's
> `disposition` is `deadline_expired`, and the turn's reply carries §10's interruption
> account. The bound is a real duration and the stall is a real one, because a fake clock
> would assert nothing about the property the acceptance sentence names. **The ledger is
> named as prompt because §1's third clause says the bound does not reach it**, so an arm
> that stalled the store instead would be asserting a guarantee this ADR does not make.

> **Normative.** **Arm 2 — the pre-registered accounting arm.** On the same fault: the
> conversation's draw counts the call **once**, the ledger claim completes with
> `interrupted_outcome` (`INDETERMINATE` for `WEB_SEARCH`) and `unknown_cost()`, and
> ADR-0194's period totals count that row exactly as they count a completed search's.
> The arm asserts the outcome member and not merely that a row exists, because `FAILED`
> is what the tree writes today.

> **Normative.** **Arm 2b — the expiry that lands before the claim.** With the gate held
> so the deadline expires inside the admission: no claim is appended, **no completion row
> is written**, no channel is opened, and the servicing still reports `DEADLINE_EXPIRED`.

> **Normative.** **Arm 3 — the pre-registered cancellation arm.** The client cancels
> mid-search: `CancelledError` is re-raised unchanged, no `SearchOutcome` is minted and no
> refusal is returned, the claim is completed with `interrupted_outcome` and an `UNKNOWN`
> cost before it re-raises, the channel is released, and the admitted call stays spent.
> Driven through `FakeWebSearcher.suspend_next` in the suite and through the production
> searcher in its own test.

> **Normative.** **Arm 4 — the pre-registered two-turn arm, read against ADR-0231 §16.**
> A conversation whose first turn searched and answered and whose second turn's search
> expires: the second turn's reply **still answers from what the conversation actually
> retains** — the tail carrying turn one's stored reply (ADR-0222 §1) and its captured
> episode (ADR-0221, ADR-0223), which is what `Planner.plan`'s `memories` carries as its
> first group (ADR-0074 §5) — and **also** states the interruption. Both halves are
> asserted, because the acceptance sentence is a conjunction and either half alone would
> pass a weaker test.

> **Normative.** **Arm 4 asserts no retained minted record, and the scenario's own words
> must not be implemented as one.** #2178's pre-registered wording — *"the reply still
> answers from turn one's records"* — reads as retention, and retention is exactly what
> ADR-0231 §16 forbids and ADR-0238 §17 relies on: a minted record is supply for one turn,
> resolves in no store, and *"a second turn re-searches … because nothing was retained"*.
> **No lane satisfies this arm by keeping turn one's minted records alive**, and a lane
> that finds the episode does not carry what the reply needs reports that as the
> scenario's finding rather than closing it with a store.

> **Normative.** **Arm 4b — the within-turn arm, which is where retained results do
> exist.** On one turn of a `USER_CHOSEN` conversation, a first servicing mints records
> and a plan revision's second servicing expires: the reply answers from the first
> servicing's records — ADR-0238 §2's third population, within a turn — and states the
> interruption. This is the arm that shows the supply is monotone under an expiry
> (ADR-0228 §7), which the cross-turn arm cannot show.

> **Normative.** **Arm 5 — the pre-registered three-bounds arm.** Three servicings of one
> deployment, each crossing exactly one bound, produce three distinct dispositions —
> ADR-0238 §11's member for the call allowance, `spend_refused` for the monetary ceiling,
> `deadline_expired` for the deadline — with no cross-talk: the exhausted conversation
> opens no channel, the spend-refused call appends no claim, and the expired one reaches
> neither the counter nor a ceiling for a second time.

> **Normative.** **Arm 6 — the guard.** `search(call, timeout=<not a timedelta>)` and
> `timeout=timedelta(0)` and a negative one each raise `ValueError`, and in each case
> nothing is revalidated, no credential is read, no gate is consulted, no claim is
> appended and no channel is opened. A suite clause, because it is what makes "there is
> always a bound" true of every `WebSearcher` this system ever wires.

> **Normative.** **Arm 7 — the signature.** The suite asserts that `search` takes exactly
> one positional-only value parameter and exactly one keyword-only parameter named
> `timeout`, and that `request` takes exactly one positional-only parameter and no
> keyword parameters — checked against the runtime signature, so an implementation that
> grew a second input fails.

> **Normative.** **Arm 8 — the fault at the send.** A connection record the searcher
> cannot read, and a ledger claim the trail refuses, each degrade the turn under ADR-0226
> §5 with every count zero and `failed` true, and each record `search_failed` as the
> disposition — asserted as **one** member for both, so a later lane splitting it is
> moving a decision.

> **Normative.** **Arm 9 — `TRANSPORT_FAILED`'s other conditions are untouched.** A
> destination that refuses the connection outright, and one that closes the channel
> mid-response, each still return `TRANSPORT_FAILED` and each still complete exactly as
> they do today — so §4 is shown to have moved one condition out of that member and to
> have changed nothing about the ones that stay, including the ones §13 records as an
> open question.

> **Normative.** **Arm 11 — the two provenance misclassifications, over the production
> searcher.** With the bound set long and the transport made to raise Python's
> `TimeoutError` of its own accord, the outcome is `TRANSPORT_FAILED` and **not**
> `DEADLINE_EXPIRED`; and with the transport made to raise `CancelledError` while nothing
> has been cancelled, the turn degrades with `SEARCH_FAILED` and **does not** end as a
> teardown. Both are asserted because an implementation that keeps a broad
> `except TimeoutError` and merely renames its refusal member passes every other arm here
> while reporting a deadline that never expired.

> **Normative.** **Arm 10 — the ledger is outside the bound, and the arm asserts the
> negative.** With the claim append held on a barrier and `search_call_deadline` set
> **shorter** than the barrier is held for: `search` has **not** returned, no
> `DEADLINE_EXPIRED` is minted, no channel is opened and no diagnostic is emitted; and
> the same with the completion append held after the callable has run. Releasing each
> barrier lets the call proceed normally. This is ADR-0192's own pinned shape, restated
> at this seam because §1's parameter is exactly the deadline a later lane would
> "helpfully" wrap an append in.

### 13. Deferred, by name, each with what fires it

- **A per-conversation bound on elapsed search time.** ADR-0238 §16 defers it and this ADR
  supplies the quantity it had none of: **a servicing's search work** — everything §1's
  window covers — is now bounded by §3's figure, so a per-conversation bound over that
  quantity is stateable. It is not a bound on a servicing's total wall-clock duration, the
  two ledger appends being outside the window by ADR-0192 §3 (§1), and a later ADR states
  its bound over the quantity §1 actually bounds. **Fired by the ADR
  that decides where such a counter lives and how it survives a deletion** — which is
  ADR-0238 §8's own analysis, unchanged — **or by the owner ruling that milestone 31's
  exit is not met by calls, cost and a per-call deadline.** **Not** fired by reintroducing
  ADR-0238 §8's deleted claim handle or settlement member, and not by an audit showing a
  conversation searching for a long time, which is the symptom rather than the trigger.
- **A per-operation figure for §1's bound**, in ADR-0228 §4's shape — one duration for
  `converse`, another for a worn-earpiece operation. §1 makes it a `Settings` or ADR
  decision rather than a Protocol change, which is the whole reason the bound is a
  parameter. Fired by an ADR that prices the operations, or by the first operation whose
  latency tolerance the shipped figure plainly misfits. Not fired by a lane finding thirty
  seconds long.
- **An honest completion outcome for a transport failure that may have followed the
  send.** §4 moves only the expiry out of `TRANSPORT_FAILED` and asserts nothing about
  what the member's remaining conditions disclosed. A channel closed mid-response and a
  refused redirect each mean the query probably left, yet the completion row records the
  classification the tree records today, and ADR-0029 §4's interrupted-outcome rule does
  not reach either because neither is a deadline or a cancellation. **Fired by an ADR
  that decides how this corpus classifies a post-send failure at the designated egress
  seam** — a question wider than search, since `send_email` has the same shape — and
  filed by this lane as **#2181**. Not fired by a lane finding the member coarse.
- **A bounded ledger append**, which is what would make §1 a wall-clock ceiling on a
  `search` frame. ADR-0192 §3 pins both appends unbounded with the reason a bound there
  would be a fiction, and §7 of that ADR already records the consequence against
  ADR-0029 §4. Fired by an ADR that gives the audit store a cancellation-cooperative
  write — an ADR-0054 change — and by nothing this seam can decide.
- **A transport-level bound** — a connect timeout, a read timeout or a socket timeout in
  `tools/egress.py`. §2's second clause leaves ADR-0231 §5's posture standing. Fired by an
  ADR that decides what a partial read means for §10's transcription; not fired by a lane
  finding the invocation deadline coarse.
- **Retrying an interrupted search.** §6 refuses it; ADR-0118 §3's reasoning is why.
  Fired by an ADR that decides retry policy for the designated egress seam as a whole.
- **A user-facing account of *how long* a turn waited, or of which bound it hit.** §10
  gives the composing stage one bare fact; the finer account is ADR-0228 §10's refusal
  restated. Fired by an ADR that decides a user-facing operational surface, not by a lane
  finding the reply vague.
- **ADR-0194 §8's default monetary ceiling (#2116).** ADR-0238 §9 declines it and this ADR
  takes none of it. Fired by ADR-0194 §8's own trigger and by nothing else.
- **A second `SearchDisposition` member for the send's faults**, splitting the store fault
  from the authorisation one (#2112's second option-shape). §8 rules one member. Fired by
  an ADR showing two operator responses the one member cannot tell apart, not by a lane
  finding a class name useful.
- **Anything §4's audit member would need a store to answer.** ADR-0226 §12 defers a
  durable, queryable surface for the audit and ADR-0231 §13 inherits it; this ADR adds two
  members to the same log event and inherits the deferral whole.

### 14. Scope, and what this records against earlier ADRs

**This ADR partially supersedes two ratified ADRs and amends one.** ADR-0231 in two scopes
and ADR-0238 in two are partial supersessions; ADR-0238 in one further scope is an
amendment. That is a classification of this change and is therefore prose rather than
marked (ADR-0089 §1). The header carries each record; what follows is the working.

**ADR-0231 §17, scope (i): the declared signature of `search`.** §17 declares the Protocol
*"with exactly three members and no more, declared with exactly these signatures"* and
gives `async def search(self, call: ToolCall, /) -> SearchOutcome: ...`. A reader holding
only ADR-0231 would refuse §1's parameter and would build a conformance suite asserting
`search` takes no keyword parameters — which is exactly what
`tests/tools/web_searcher_contract.py` does today. ADR-0070 §1's test is met, and the
scope is that one signature: the three-member closure, `request`'s signature, the
positional-only rule for both **value** parameters, the `name` clauses and the
no-store-no-supply-no-policy clause all bind verbatim.

**ADR-0231 §17, scope (ii): `SearchRefusal`'s count.** §17 closes it *"at exactly six
members"*. A reader holding only ADR-0231 would refuse §4's seventh. The scope is the
count alone; the six members, their values, the added-to-and-never-renamed rule and the
raise-for-nothing posture stand, and §4 is written inside them.

**ADR-0231 §5's field count is *not* recorded against, and §13's disposition count is
*not* recorded against ADR-0231.** §5's clause is scoped to what ADR-0231 adds (see
Context), so §3's field is a stacked addition. §13's fifteen-member closure has **already**
been superseded by ADR-0238 in that count alone, so the live statement of that count is
ADR-0238 §11's sixteen — and a clause that no longer stands cannot be superseded a second
time. Recording against it would put a second, weaker pointer on a line that already tells
a reader to look at ADR-0238, which is the accumulation ADR-0070 §4 permits being used to
say the same thing twice.

**ADR-0238 §13, scope (i): the `WebSearcher` limb.** §13 rules that *"`ActionPolicy`,
`AuditTrail`, `MemoryStore` and `WebSearcher` each gain no member, no argument and no
widened return"*. §1 gives `WebSearcher` an argument. A reader holding only ADR-0238 would
read that clause as forbidding it, so §1's test is met; the scope is `WebSearcher` alone
and the argument limb alone, since no member and no widened return is added.

**ADR-0238 §11, scope (ii): `SearchDisposition`'s count.** §11 closes the enumeration at
sixteen and adds *"no lane reads this as licence to add a seventeenth"*, which is a
sentence written to stop exactly the kind of lane this is — and it is stopped: the
seventeenth and eighteenth arrive by a ratified ADR, which is the instrument §11 reserves.
The scope is the count and that sentence; injectivity, the no-message rule, the
`NO_RESULT` exclusion and §11's audit clauses stand entire.

**ADR-0238 §8: an amendment, not a supersession.** ADR-0070 §1's test is applied to §8's
text, not to its conclusion. What becomes false is a **premise it recites** —
*"`WebSearcher.search(call, /)` takes no timeout and no deadline"* and *"Nor is there a
per-call bound to substitute"* — and a reader holding only ADR-0238 would go on believing
no bound exists to derive from. What §8 **decided** is untouched in every clause: calls and
not time; one `Settings` field and not two; no stored elapsed counter, provisional charge
or `SearchClaim` handle; the counter on the conversation record; the ADR-0228 §4
correction. **ADR-0060's own header is the precedent and it is directly on point** —
ADR-0118 put a deadline over a seam and was recorded on ADR-0060 as *"§5's `Embedder`
assessment amended by ADR-0118"*, because §5's assessment of an abandoned worker was a
premise the deadline overtook while §1's rulings stood. ADR-0238's `Status` line has no
leading token, so under ADR-0082 §2 the qualifier belongs on the line and the dated note
carries the substance.

**Stacked additions, recorded here and nowhere else** (ADR-0082 §1): §3's one `Settings`
field; §4's `SearchRefusal` member and its disposition; §8's `SEARCH_FAILED`; §9's
three-bounds statement; §10's fact and its carrier obligation; and §5's completion rule,
which contradicts no sentence of ADR-0192 or ADR-0029 and instead applies ADR-0029 §4's
existing rule at a seam that was getting it wrong.

**ADRs a reader would expect to have moved, and which did not.** **ADR-0029** — §4's
clauses are stated over `ToolInvoker.invoke`; adopting their shape at a second route
contradicts none of them, and its *"`ToolDefinition` does not gain a timeout field"* is
relied upon by §1 rather than moved. **ADR-0060** — §1's three clauses bind entire and §7
adds nothing to them; this ADR writes no new module-level cancellation text. **ADR-0118**
— §2's decorator ruling is about `Embedder` and is not narrowed; §2 above argues from
different facts at a different seam rather than reversing it, and §9's caller test is
applied as written and comes out the other way. **ADR-0192** — §1's claim placement and
§3's completion-on-every-exit rule are relied upon exactly as ratified; §5 changes which
`ToolOutcome` a completion carries at one seam, which is ADR-0029 §4's computation and not
ADR-0192's. **ADR-0194** — §1's four fields, §2's estimate/reported boundary and §3's
admission order are untouched; §3's `ConfigurationError` shape is copied, not moved.
**ADR-0226 §5** — its all-or-nothing degradation is unchanged by §8. **ADR-0228** — §4's
planning budget, §10's carrier and its no-duration rule bind entire; §10 above adds a
third fact in §10's shape rather than moving it. **ADR-0230, ADR-0235, ADR-0236,
ADR-0237, ADR-0240** — relied upon as written. **ADR-0014, ADR-0016, ADR-0089 and
ADR-0148** — relied upon as written.

### 15. Marking, review and ratification

> **Normative.** This ADR is marked under ADR-0089: the block quotes above are the whole
> of what it obliges, and unmarked text is read to determine what a marked clause means
> and never supplies an obligation.

What binds is **sixty-six marked clauses**: §1's seven, §2's two, §3's five, §4's five,
§5's four, §6's three, §7's five, §8's four, §9's six, §10's five, §11's four, §12's
fifteen, and this section's one. §13's list, §14's classification and every argument in
this document are deliberately unmarked: they are deferral, attestation and argument,
which ADR-0089 §1 classifies as non-normative however load-bearing.

**Required reviews: adversarial *and* architecture.** This is a contract-surface change in
`CONTRIBUTING.md`'s sense — it adds a parameter to a `core/protocols.py` member, a member
to a `core/types.py` enumeration and a field to `core.config.Settings`, and it moves
clauses of ADR-0231 and ADR-0238 — so it owes both lenses under ADR-0015 §1. It is
drafted, reviewed and revised as `Proposed`, its status flipped only once both required
reviews return clean on one tree, and the route is `CONTRIBUTING.md` → "Finishing an ADR
PR". Nothing implements against it until it has merged (ADR-0015 §5, golden rule 5).

## Consequences

- **A stalled provider stops being able to hold a turn open.** The bound existed; what did
  not exist was any route from a deployment to it, any statement of it at the contract, or
  any way for a second `WebSearcher` to be held to it. All three arrive together. **A
  stalled audit store still can**, and §1 says so rather than implying otherwise: that is
  ADR-0192 §3's ratified trade and this ADR does not reopen it.
- **The audit can tell four conditions apart that were previously two.** An outage, a slow
  provider, a fault at the send and a completed-but-empty search each get their own value
  in the one event an operator reads over a population.
- **One live defect is corrected.** An expired search stops recording that it certainly
  did not act. That makes more rows `INDETERMINATE`, which is the honest state and is the
  state a cancelled search already records.
- **`WebSearcher` becomes marginally harder to implement**, by one required argument and
  one guard. That is the cost of the seam owning the deadline, and ADR-0029 §4 already
  paid it once at `invoke`.
- **The per-conversation elapsed bound becomes a decision somebody can take.** It has been
  deferred since ADR-0238 for want of a quantity; it now has one, and §13 says what fires
  it.
- **What is harder:** three bounds now have to be kept apart by discipline as well as by
  name, and §9 is where a later lane's collapse of two of them will be caught. And a
  deployment that sets `search_call_deadline` too low will see `deadline_expired` where it
  used to see results — which is the bound doing its job, and is why §4's member exists
  rather than a quieter one.

## Alternatives considered

**A decorating `WebSearcher` wired at composition, as ADR-0118 chose for `Embedder`.**
Refused in §2: it cannot classify its own expiry without performing the cancellation-to-
outcome conversion the Protocol forbids, it stands outside the claim and the admission
window, and it forecloses a per-operation figure. ADR-0118's own §9 test is what decides
it, applied honestly and coming out the other way.

**A `Settings` field consumed at composition into the existing constructor parameter, with
no Protocol change.** The smallest change, and it is the one this ADR does not take. It
leaves the bound invisible at the seam, so a caller still cannot know whether it can be
hung and a second `WebSearcher` is bounded only if someone remembers; it fixes the
per-deployment figure for every operation, which ADR-0228 §4 has already ruled the wrong
key for a latency tolerance; and it would still need this ADR's §4 and §5 to make an
expiry legible, so it saves a Protocol change and nothing else. §3 takes its `Settings`
half, which is the part that was genuinely missing.

**Both — a Protocol parameter *and* a constructor override kept as a fallback.** Refused
in §3: two sources for one bound is a searcher able to disagree with its caller about the
window it is running in, and the ADR-0029 §4 arrangement this seam is modelled on has
exactly one.

**Leaving an expiry as `TRANSPORT_FAILED` and distinguishing it in the log line instead.**
Refused in §4 and §5. It would leave `_result_of` unable to classify the completion row:
ADR-0029 §4's rule is stated over a deadline expiry and a cancellation, so a mapping from
one member covering both an expiry and a refused connection cannot apply it to the first
without applying it to conditions §4 does not reach. The audit argument alone would not
have been enough; the ledger argument is.

**Raising a named error class on expiry, as ADR-0118 §5 does for the embedder.** Refused:
ADR-0231 §17's raise-for-no-source-reason posture is what makes a non-yield *"a value the
audit can count and the turn can ignore"*, and an exception here would make ADR-0226 §5's
degradation the servicer's problem to catch correctly at every call site — the failure
mode that posture exists to prevent. ADR-0118's seam has no refusal vocabulary to return
into; this one does, and §4 uses it.

**Ruling #2112 the other way — a clause saying a fault at the send is ADR-0226 §5's
degradation and nothing more.** A defensible answer, and it is what the tree does today.
Refused in §8 because `SearchDisposition`'s stated design is one member per stage and the
send is the one stage with none, so the absence reads as an omission rather than as a
decision every time someone opens the enumeration.
