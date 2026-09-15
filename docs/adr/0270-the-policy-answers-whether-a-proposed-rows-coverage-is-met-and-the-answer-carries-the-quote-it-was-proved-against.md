# 270. The policy answers whether a proposed row's coverage is met, and the answer carries the
quote it was proved against

- Status: Proposed
- Date: 2026-09-15

## Context

### Where this comes from

Issue **#2401**, booked by ADR-0267 §10 as *"the gap … in ratified ADR-0266"* and named there by
what fires it: *"a Protocol member answering, for a concrete request and a proposed row's coverage,
whether that coverage is met — which widens a `core` Protocol and so owes its own ADR merged
first"*. This is that ADR.

### The gap this closes, stated as the failure the corpus has today

Four ratified clauses stand without a seam joining them.

- **ADR-0266 §7** puts condition 6's *"One implementation, in `permissions`"*, and restates
  ADR-0254 §1's completeness condition over it: *the row the proposal would write satisfies
  condition 6 for this request*.
- **ADR-0254 §15** rules that an `Authorization` is *"written and settled by `orchestration` and by
  nothing else"*, and **§1** makes a path-(i) proposal conditional on that completeness.
- **Golden rule 1** forbids `orchestration` importing `permissions`.
- **No clause of either decision says how a component outside `permissions` obtains condition 6's
  answer.**

So the proposal path is writable only by re-implementing the rule where it may not live.
`orchestration/authorizing.py::proposed_authorization` evaluates the completeness condition in
place today, and its own docstring records that it is *"only ever vacuous"* (#2373): a request
carrying any user-facing argument proposes no row at all. That is the fail-closed direction and
the ruled one while no member can be minted — but the moment a `MONEY` member can be met, which
ADR-0266 §7's evidence route and ADR-0267's quote together make true, the in-place evaluation stops
being vacuous and becomes a second implementation of a rule ADR-0266 places in exactly one
component.

### The tree, read rather than assumed, at `origin/main` `27b540c3`

- `core/protocols.py`'s `ActionPolicy` carries **two** members, `decide` and `resolve`, and
  `orchestration`'s `StepRunner` already holds one: it calls `decide` before the claim and
  `proposed_authorization` beside it, in one method. **No new seam and no new composition-root
  wiring is needed to ask it a third question.**
- `permissions/_coverage.py` holds condition 6 as `covers`, `covers_arguments` and `uncovered`,
  over a `CoverageSubject` read off the request in one observation. It is module functions, holds
  no store and no seam, and is called by the policy alone.
- **`BoundedArgument`, `CoverageMember.kind` and `ActionRequest.intended_action` are not on this
  tree** — ADR-0266's L1 is in flight (PR #2408) — and **`ActionQuote`, `QuoteView` and
  `GoalQuotes` are not either**, ADR-0267's Q1 being unbriefed. Every operand of the evidence route
  is therefore still to land, which is what §6 below cuts the lane against.

### What this ADR is not allowed to settle

Anything else in ADR-0266 or ADR-0267. It adds **one** member answering **one** question, and it
neither revisits the two routes, nor the quote's carrier, producer or freshness, nor what a
declaration declares, nor what a confirmation renders.

## Decision

### 1. `ActionPolicy.coverage_met`: one member, and it answers condition 6 and nothing else

> **Normative.** `core/protocols.py`'s `ActionPolicy` gains **one** member and no lane adds a
> second: **`async def coverage_met(self, request: ActionRequest, coverage:
> tuple[CoverageMember, ...]) -> CoverageAnswer`**, answering whether `coverage` — the coverage a
> row this system would write would carry — satisfies **ADR-0266 §7's condition 6** for `request`.
> It is **`async`** because the evidence route reads a durable seam, `GoalQuotes.for_action`
> (ADR-0267 §5), on `CLAUDE.md`'s own rule and as `GoalAuthorizations.live_for` is. Cancelling it
> is governed by `core/protocols.py`'s cancellation clause (ADR-0060) and its observation of its
> arguments by ADR-0065's, like every member of that module. This is a **BREAKING** contract change
> to `core/protocols.py` under golden rule 5 and is flagged as one.

> **Normative — it is on `ActionPolicy` and not on a narrow face beside it, and the ground is that
> the caller already holds one.** `StepRunner` is handed an `ActionPolicy` today and calls `decide`
> in the same method that builds the proposal, so the member costs **no new seam, no new
> composition-root wiring and no new object for a lane to forget to pass**. The narrow-face
> argument ADR-0097 §3 and ADR-0193 §1 make is about denying a component a capability it should not
> have; this member **denies rather than grants** — it returns no ruling and writes nothing (§4) —
> so a separate face would deny its caller nothing it does not already hold and would buy only a
> second thing to wire.

> **Normative — it takes the coverage tuple and never the row.** ADR-0254 §15 rules that no
> `ActionPolicy` writes or settles an `Authorization`; handing the policy the row about to be
> written would put one in its hands for the one question that does not need it. Condition 6 is
> stated over the request's user-facing arguments, its declaration's `bounded_arguments`, its
> `intended_action` and the row's `coverage`, and the first three are on the request — so the
> request and the tuple are the whole operand, and `id`, `goal`, `tool`, `account`,
> `destinations`, `proposed_at`, `expires_at`, `confirmation`, `supersedes` and `disposition` are
> read here by nothing.

> **Normative — it evaluates condition 6 and no other condition.** Not ADR-0254 §3's conditions 1
> to 5 — there is no live row for them to be taken over, a proposal being written `PROPOSED`, which
> is ADR-0266 §7's own reason for restating §1's condition over condition 6 alone. Not ADR-0254
> §6's floors: §1's *"the proposal reads none of §6's floors, and that is deliberate"* binds entire
> and this member reads none either, so a request whose binding carries
> `planned_with_external_content` is answered on condition 6 exactly as one that does not. Not
> §12's ladder, and not §1's other three proposal conditions, which the writer takes for itself.

### 2. `CoverageAnswer`: a closed result, and it carries the quote the answer was proved against

> **Normative.** `core/types.py` gains **`CoverageAnswer`**, a frozen model with `extra="forbid"`
> whose fields are exactly two: **`met`**, a `bool` — whether `coverage` satisfies condition 6 for
> the request — and **`quote`**, an `ActionQuote | None` defaulting to `None`, the **governing
> quote** (ADR-0266 §7) a met answer was proved against. A **model validator** refuses a `quote`
> present where `met` is `False`. The field list is **closed**, and a lane adding a member is
> changing this decision rather than implementing it. Adding the type breaks no decode and no
> conforming implementation; the member above is the breaking half.

> **Normative — why the quote rides on the answer, and it is the residual ADR-0267 §10 books.**
> ADR-0267 §1 gives a path-(i) row `quoted`, *"the governing quote for the request's intended
> action in the goal read the row was built from"*, and §10 books as this amendment's question
> *"whether the row records the quote that answered it"*, observing that *"until a seam returns the
> quote it read, `quoted` and condition 6's operand are two reads and can differ"* where a refresh
> lands between them. **It returns it**, and the writer sets `Authorization.quoted` from this field
> and from nothing else — so the figure the user is shown is the figure the completeness condition
> was satisfied against, one read and not two. **The selection stays ADR-0267 §5's**, *"`permissions`
> takes the last member of what comes back"*: a second component choosing a governing quote would
> be a second implementation of the rule ADR-0266 §7 places in one.

> **Normative — `quote` is present exactly where a quote governed a met answer, and its absence is
> never a licence.** A met answer over a coverage carrying a `MONEY` member carries the quote that
> met it, ADR-0266 §7 admitting no other way for such a member to be met. A met answer over a
> coverage carrying no such member carries none — today's vacuous case, an empty `coverage` over a
> request carrying no user-facing argument, is met with `quote` `None`. **No component reads a
> `None` `quote` as a met `MONEY` member proved by something else**, there being nothing else, and
> none supplies, defaults or infers one.

> **Normative — the answer carries no reason, and that is decided rather than deferred.** Where
> `met` is `False` no row is written, `Confirmation.authorization` is absent (ADR-0254 §11) and the
> one call is confirmed under ADR-0148 §3's route (a) — so no surface renders a projection of a row
> that does not exist, and no caller on this tree has a use for **which** conjunct failed. The
> account of an uncovered request a user does see is `decide`'s, taken at dispatch over a live row
> (ADR-0254 §4), and it is untouched. **A later decision that gives a caller a use for the reason
> adds the field**; this one mints no vocabulary with no reader.

### 3. Where it is consulted, and where it is not

> **Normative — one question, one answerer.** Where a component that is not `permissions` needs
> condition 6's answer about a row it would write, **it obtains it from this member and by no other
> means**: it re-implements no conjunct of condition 6, selects no governing quote, compares no
> arguments digest, reads no `BoundedArgument` and takes no `ValueBound` comparison. That reaches
> **ADR-0254 §1's completeness condition**, which ADR-0266 §7 restates over condition 6 and which
> §1 states over path (i) **and** path (iii); and it reaches **ADR-0254 §5's correction test**, as
> ADR-0266 §9 restates it — *"an argument the row would not cover under condition 6 once the
> correction is applied"* — on path (ii). **This decision cuts a lane for none of the three** (§6):
> path (i) is the only one with a writer on this tree, and the rule is stated over the question
> rather than over the lanes so that a later writer inherits it rather than re-deciding it.

> **Normative — ADR-0254 §13's recheck is untouched, and this member is not it.** The coverage
> comparison *"taken at `ActionPolicy.decide`, on the concrete request, at every dispatch"* stands
> exactly as §13 and ADR-0266 §7 state it, over a **live** row and all six conditions, and nothing
> here relaxes, replaces or pre-empts it. **No answer this member returns is cached, carried to a
> dispatch, stored on a row, or read by any later comparison**: §13's *"no cached coverage verdict
> anywhere"* binds this member exactly as it binds every other, and a proposal-time answer answers
> that proposal and is discarded. The one value that survives the call is `Authorization.quoted`,
> which ADR-0267 §1 makes provenance *"no comparison of any decision reads"*.

### 4. What it never does

> **Normative.** It **rules nothing**. It returns no `PermissionRuling`, so it has no field in
> which to allow, deny or confirm; it sets no `authorised_by`, no `authorised_subject` and no
> `authorised_goal`; it is no route of ADR-0148 §3 and clears no floor of any of them. The ruling
> on the request is `decide`'s, unchanged, and a met answer authorises nothing by itself.

> **Normative.** It **establishes nothing and records nothing**. It writes and settles no
> `Authorization` — ADR-0254 §15's writer clause binds entire — mints no `CoverageMember`, mints no
> quote, writes no `ActionQuote`, records no `PermissionDecision` and touches no store. **And it
> reads no model output**: ADR-0254 §9's no-model clause and ADR-0266 §8's binding entire, no
> nomination of an argument, a kind, a member, a bound or a quote reaches it or is read by it.

> **Normative — a fault is never an absence, and the disposition is ADR-0254 §1's own.** Where
> `GoalQuotes.for_action` raises `AuthorizationError` (ADR-0267 §5), this member **propagates it**:
> no implementation converts it into `met=False`, into an empty tuple of quotes, or into a met
> answer. **A component that asked writes no row where the member faults**,
> `Confirmation.authorization` is absent and the one call is confirmed under route (a) — §1's own
> disposition for a failed completeness condition, reached by one further case. **No new error
> class is minted** and no caller falls through to the argument route.

> **Normative — a policy that cannot read a quote answers `met=False`, and never met.** An
> implementation constructed with **no** `GoalQuotes` answers `False` for any `coverage` carrying a
> member the evidence route alone can meet — which is every `MONEY` member (ADR-0266 §7) — and
> answers with `quote` `None` in every case. It invents no quote and returns no met answer on the
> strength of a quote it did not read. That is `decide`'s own *"no authorisation source"* floor
> read one member over, and it is what makes the writer's call behaviour-preserving on a tree that
> carries no quote: the empty coverage this system proposes today is still met exactly where it is
> met today.

### 5. What this records, and what it declines to record, under ADR-0082 §1

> **Normative — ADR-0266 §7's last clause is superseded in one limb, and its other two limbs bind
> entire.** That clause reads *"At `ActionPolicy.decide`, on the concrete request, at every
> dispatch, with no cached verdict anywhere, which is where ADR-0254 §13 puts it … One
> implementation, in `permissions`, and §5's mint runs none of it."* Read whole it answers **where
> the comparison is taken** exhaustively, and a reader holding only §7 puts condition 6 behind
> `decide` and exposes no face — leaving the answer unobtainable to the component ADR-0254 §15
> obliges to write the row, which is #2401. **The limb naming `decide` as the only site is
> replaced**: the comparison is taken at `decide` at every dispatch **and** at `coverage_met`
> before a row is written. **The one-implementation limb is not weakened but kept** — this member
> is that implementation's face and not a second one — and the no-cached-verdict limb binds entire
> (§3).

> **Normative — ADR-0266 §11's lane-ordering clause is superseded in its Lane-2 limb alone.** §11
> rules that *"ADR-0254 §20's Lane 2 is briefed after the quote decision (§10) rather than after
> these two"*. Lane 2 owns the proposal path and its path-(i) writer, so it is the lane that calls
> this member; briefed on §11's ordering alone it would land before the seam exists and would
> evaluate condition 6 in `orchestration`, which §7 forbids. **Lane 2 is briefed after the quote
> decision and after this decision's own lane** (§6). Every other limb of §11 binds entire — L1's
> and L2's surfaces and arms, *"two lanes and no third"* for that decision's own implementation,
> L1's wait on ADR-0254 §20's Lane 3, the wire clause and the no-migration clause.

> **Normative — no record is owed against ADR-0254, and the working is stated rather than
> assumed.** §1 states the completeness condition, its four conditions and its disposition, and
> says **nothing** about which component evaluates it or how one obtains the answer — which is
> exactly what ADR-0267 §10 records as not decided — so no sentence of §1 becomes false or
> over-wide. §13's recheck-at-`decide` and its no-cached-verdict rule stay true word for word (§3).
> §15's writer clauses stay true, no `ActionPolicy` writing or settling a row here (§4). **And
> §16's roster is untouched**: it enumerates *"the `core` surface **this decision** adds"*, and
> `CoverageAnswer` is added by this decision and by no lane of that one, so its count stays right —
> which is what distinguishes it from the scopes ADR-0266 and ADR-0267 took there, each of which
> moved a type or a field §16 itself enumerates.

> **Normative — no record is owed against ADR-0267 either.** §5's `GoalQuotes` shape, its keyed
> read, its no-predicate rule, its fault direction and its composition-root clause are consumed
> unchanged; §1's `quoted` is populated from this answer rather than redefined; and §10's own entry
> is **fired** rather than contradicted — it names this amendment as what fires it and states the
> two-reads residual as holding *"until a seam returns the quote it read"*. §11's *"condition 6 is
> evaluated in no lane of this decision"* stays true of both its lanes.

### 6. The lane cut, and the arms this decision owes

> **Normative.** This ADR is ratified and merged as its own PR before anything implements against
> it (ADR-0015, golden rule 5), and it is implemented in **one lane and no second**:
> `core/protocols.py`'s member, `core/types.py`'s `CoverageAnswer`, the obligations above in the
> shared conformance suite, the canonical fake in `ai_assistant.testing`, and the one
> implementation in `permissions`, which is `_coverage.py`'s condition 6 reached through the
> policy. **The call site is not this lane's**: `orchestration`'s in-place evaluation is replaced
> by the call in **ADR-0254 §20's Lane 2**, which owns the proposal path and its path-(i) writer,
> and which is briefed after this lane (§5). **This lane writes no `Authorization`, wires no
> consequential capability and touches no file under `orchestration`.**

> **Normative — the lane is briefed after ADR-0266's L1 and after ADR-0267's Q1, and the reason is
> that every operand is theirs.** L1 lands `BoundedArgument`, `CoverageMember.kind`,
> `ActionRequest.intended_action` and §7's two routes in `permissions/_coverage.py`; Q1 lands
> `ActionQuote`, `GoalQuotes` with its triad, and `for_action` wired into the evidence route.
> Without L1 there is no condition 6 in the shape this member answers; without Q1 there is no
> `ActionQuote` for `CoverageAnswer` to carry and no quote for a `MONEY` member to be met by.
> **Where either is not in its base, this lane is not briefed** — ADR-0266 §11's own shape for L1's
> wait on Lane 3. **The lane re-takes that reading at its own base and states what it found.**

> **Normative — the tree this lane leaves is conforming and fail-closed, and nothing is a second
> implementation in the interval.** Until Lane 2 moves the call site, `orchestration` keeps its
> present refusal — no row is proposed for a request carrying any user-facing argument — which
> **compares nothing**: it evaluates no member, takes no route and reads no quote, so it is a
> refusal and not a rival implementation of condition 6. It is strictly more restrictive than the
> member's answer, so the interval costs questions and authorises nothing (ADR-0084 §3).

> **Normative — neither `PROTOCOL_VERSION` nor `PlanExport.schema_version` moves, and no stored
> record gains a field.** `CoverageAnswer` crosses **no frame**: it is returned across a Protocol
> within one process, is a field of no model any frame carries and of no stored record, and
> `wire/codec.py` renders none of it. An `ActionQuote` riding inside it crosses nothing it does not
> already cross. **No row is migrated, edited or dropped**, and no `Settings` field, deployment flag
> or configurable figure is added.

> **Normative — the lane ships the four arms below, each over controlled fakes, and it is not
> complete without them.** No arm asserts anything its own tree cannot produce, and none is
> demonstrated against a live integration.

1. **The vacuous case, preserved exactly.** An empty `coverage` over a request carrying **no**
   user-facing argument answers `met` `True` with `quote` `None`; the same empty `coverage` over a
   request carrying one user-facing argument its declaration declares at no kind answers `met`
   `False`. That is `proposed_authorization`'s present behaviour, so Lane 2's call-site change
   preserves what this tree does today rather than changing it.
2. **A `MONEY` member and the governing quote**, over quotes **constructed** on a goal. Against a
   quote naming the request's `intended_action`, taken over the request's own arguments, at
   `"120"`/`"EUR"`, a `coverage` carrying one `MONEY` member bounded at `150`/`EUR` answers `met`
   `True` with `quote` **that** quote; at `"170"` it answers `False` with `quote` `None`; at
   `"120"`/`"USD"` it answers `False`; with **no** quote naming that action it answers `False`; and
   an implementation holding no `GoalQuotes` answers `False` for that same pair.
3. **It rules nothing, records nothing and caches nothing.** The member returns no
   `PermissionRuling`, writes no `Authorization` and appends to no store; two calls with equal
   arguments each read the seam, no answer being memoised between them or carried to a later
   `decide`; and a `for_action` raising `AuthorizationError` **propagates** rather than answering
   `met` `False`.
4. **Condition 6 and no other condition, and the result's one refusal.** A `coverage` that
   satisfies condition 6 is answered `met` `True` on a request whose `egress_binding` carries
   `planned_with_external_content`, on a request whose goal holds no live row of that pair, and
   whatever §12's ladder would yield for it — those being §1's other conditions and §6's floors and
   not this member's. And `CoverageAnswer(met=False, quote=<a quote>)` is **not constructible**.

### 7. This ADR classified, marked, and how it is ratified

> **Normative.** Under ADR-0070 §1's test this is a **supersession and not an amendment**: a reader
> holding only ADR-0266 §7 and §11 would act differently, so §5's two scopes take the partial form
> (ADR-0070 §3, §4). It is a **contract** decision — it widens `core/protocols.py` — so under
> ADR-0015 §1 it is reviewed by **both** lenses while `Proposed`, ratified by `just adr-ratify`'s
> one-line flip, and merged as its own PR before anything implements against it.

> **Normative.** This ADR is **marked** under ADR-0089: every obligation it imposes is in a clause
> of §2's grammar, and unmarked text beside a mark is read to determine what that mark means and
> supplies no obligation of its own (ADR-0089 §3).

> **Normative — the record this change writes, and it is the whole of it.** ADR-0266 gains the
> **appended dated note** ADR-0070 §1 requires, stating both scopes of §5 in full — the invariant
> half of the record in ADR-0082 §2's terms, and the shape the decision that last superseded a
> clause of that document used on it. **Its `Status` line is not edited here.** That item is
> already irregular — its value is followed by a multi-line continuation recording what ADR-0266
> *supersedes*, dense with `ADR-NNNN` references — so leading it with `Partially superseded by`
> would put ADR-0070 §4's extraction invariant, *"every `ADR-NNNN` after the leading `Partially
> superseded by` is a target"*, at risk over a line this decision did not write, and appending a
> qualifier would extend a sentence that does not parse as one. **Repairing another decision's
> header is not this change**: the residual is filed as an issue and cited here. **No other ADR's
> header is edited**, and no file under `src/` or `tests/` is touched.

## Consequences

**The proposal path becomes writable at all.** Today it is writable only vacuously, and the one
route to making it general crosses golden rule 1. After this, `orchestration` proposes a row whose
coverage it can neither evaluate nor second-guess, and the component that owns condition 6 keeps
owning it — the seam is the whole of what joins ADR-0266 §7 to ADR-0254 §15.

**The row records the figure it was actually proved against.** ADR-0267 §7 requires the
confirmation to render the price the answer was taken over, and §10 records that two reads can
differ. One read now answers both, so a refresh landing between the completeness test and the write
cannot make the user's screen disagree with the test that put it there.

**What becomes harder.** `ActionPolicy` gains a third member, so every conforming implementation
and the canonical fake grow one — a cost golden rule 5 makes visible rather than cheap. Two lanes
now queue behind a third: ADR-0254 §20's Lane 2 and, with it, ADR-0267's population of `quoted`
wait on this decision's lane, which itself waits on ADR-0266's L1 and ADR-0267's Q1. And a caller
that wants to know **why** a coverage was not met has no field to read; the reason is booked to the
decision that gives one a reader.

**What would trigger revisiting this.** A second component outside `permissions` needing condition
6's answer for something other than a row it would write — the member is stated over that case and
no other. A surface that renders a refused proposal, which would give the reason a reader. And a
decision that makes a `PERIOD` or a `TERMS` member meetable by something the argument route cannot
supply, which would put a second operand beside the quote on the answer.

## Alternatives considered

**A narrow Protocol beside `ActionPolicy`**, on ADR-0097 §3's and ADR-0193 §1's pattern. Declined in
§1: those faces exist to **deny** a component a capability, and this member denies its caller
nothing it does not already hold — `StepRunner` has the policy in hand. A second object would be a
second thing for a composition root to pass and a lane to forget, bought for no guarantee.

**Returning a bare `bool`.** Declined in §2, but narrowly: the reason for a refusal is genuinely
unused, and a closed result carrying it would be a vocabulary with no reader. What a `bool` cannot
carry is the **governing quote**, and without that `Authorization.quoted` is a second read of the
same fact — ADR-0267 §10's own residual — or a second selection of the governing quote outside
`permissions`, which ADR-0266 §7 forbids. The result is the narrowest shape that carries it.

**Passing the proposed `Authorization` itself.** Declined in §1: it hands an `ActionPolicy` the row
ADR-0254 §15 rules it may never write, for a question that needs only the request and the coverage
tuple. Narrower is not merely tidier here — it makes the writer clause true by construction.

**Leaving the evaluation in `orchestration` and calling it a permitted duplication.** Declined: it
is exactly the second implementation ADR-0266 §7 forbids, and the two would be free to disagree the
moment a member could be met. The fail-closed direction of today's in-place refusal is not a defence
of it — it is why the interval before Lane 2 is safe (§6), not why the duplication could stand.

**Evaluating the completeness condition inside `permissions` by handing it the whole proposal
decision.** Declined: that moves ADR-0254 §1's other three conditions, §12's ladder and the
supersession choice into the policy, which would put the writing of an `Authorization` one step from
a component §15 excludes from it.
