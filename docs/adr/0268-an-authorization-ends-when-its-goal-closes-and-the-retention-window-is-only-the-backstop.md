# 268. An authorization ends when its goal closes, the retention window is only the
backstop, and an offered change carries the price its acceptance authorises

- Status: Proposed
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **four scopes, and §7 shows the working for each. §1's `AuthorizationDisposition`
  clause**, in its closure and its retired enumeration: *"closed at exactly **six** members"*
  becomes **seven**, gaining **`GOAL_CLOSED`** — valued by lower-cased member name, meaning
  *this authority ended because its goal closed*, and **retired** — and *"`DECLINED`,
  `EXPIRED`, `REVOKED` and `SUPERSEDED` are retired: no edge leaves them"* enumerates four
  where there are now five. §1's own *"The vocabulary is added to and never renamed"* is the
  licence and is unmoved. **§1's transition graph, in its edge count alone**: *"stated whole,
  and there are exactly **five** edges"* becomes **six**, the sixth being
  `ESTABLISHED → GOAL_CLOSED`. Its other two assertions stand verbatim and are relied on —
  `PROPOSED` and `ESTABLISHED` stay the two members an edge leaves, and no other edge exists —
  and `settle`'s own clause stands but for the count, still refusing every move that is not an
  edge and every move out of a retired disposition; `AuthorizationSettlement` is unmoved at four
  members and `WOULD_DUPLICATE` is unreachable on the new edge. **§1's `PROPOSED`-row clause
  binds verbatim**, no edge leaves `PROPOSED` into the new member, and §1's field list, its
  three write paths, its uniqueness rule, its conditional supersession and its liveness
  predicate are untouched. **§16's store roster, in the signature count alone**: the **eight**
  signatures stated *"in full, because a roster of names is not a contract"* become **nine**,
  gaining `end_for_goal(goal, /, *, at) -> int`, which in one indivisible step settles every
  `ESTABLISHED` row of a goal — live and lapsed — to `GOAL_CLOSED` and answers how many it
  moved, reading no clock and evaluating no liveness. `GoalAuthorizations` and
  `AuthorizationResolution` gain nothing, so §16's three-faces construction stands entire, as do
  its detached-snapshot rule, its clock disciplines, its `standing` clause, its data-rights
  clause and its `PROTOCOL_VERSION` clause, which this decision does not fire — no
  `Authorization` crosses whole. §16's `core/types.py`, `core/errors.py` and `PermissionDecision`
  rosters take **no scope**: no type, no field and no class is added. **And §20, in two limbs**:
  Lane 1's *"The **eight** store signatures"*, which goes with §16's roster; and **arms 37 and
  55, each in its edge count and its retired-disposition enumeration alone**, which now run over
  six edges and five retired dispositions — every assertion of both standing verbatim, their
  subject being `settle`. Every other arm is untouched, arm 4's revocation-between-`live_for`-
  and-`record` case conspicuously so, and §20's lane cut and its wire clause bind entire.
  **§§2-15 and §§17-22 stand as they are, but for the limbs of §1, §16 and §20 named above**,
  and several are what this decision rests on: §7's route-(d) invariant needs no conjunct, its
  own ground — *"every other disposition is retired and none of them is live"* — being true of
  the new member; §11's listing, announcement and revocation surfaces gain nothing; §12's
  expiry-taken-once and no-deletion rules bind entire and no instant is moved; §13's recheck and
  its stated residual are unnarrowed; and §15's writer clauses reach the new member unchanged.
- **Partially supersedes** [ADR-0256](0256-an-authorization-with-no-stated-instant-and-no-goal-deadline-takes-the-retention-window-its-acts-own-record-lives-under.md)
  — **one scope. §1's bound clause, in the direction of the bound alone**, and with it that
  decision's title: *"**A row written on this rung is bounded by the turn-retention window in
  force at its own write, measured from `proposed_at`, and by nothing longer**"* stays true as an
  **upper** bound and stops being the horizon — such a row now ends at the **earlier** of that
  instant and its goal's closure. A reader holding only that decision reads the window as when
  the authority ends, and would report a live authority over a finished request for the rest of
  it. **Every other clause binds entire and several are what this rests on**: §1's rung, its
  `proposed_at`-only read, its no-new-reader rule and its illustrative list of rows that outlive
  an act's record; §2's `Settings`-gains-nothing, read-once and fail-closed arithmetic; §3's
  keep-turns-forever case, which writes no row at all; §4's rendering and its refusal of a
  `source` member; §5's narrowing correction; and **§6 entire**, whose *"No row is moved,
  shortened or settled by anything that happens to the act's own record"* is stated over the
  **act's record** and is reached by no clause of this decision — what ends a row here is the
  **goal's** status, which is neither an episode nor a conversation. §§7-11 stand as they are.
- Date: 2026-09-15

## Context

### Where this comes from

The owner's ruling on #2255 of 2026-09-14, quoted rather than summarised, because every
clause below is stated against it:

> **an authorisation lasts for its request, and a request ends when the action is done.**
>
> - A request is judged against the world as it is now. Forecast dry → booking executes →
>   verification confirms → goal complete → **the authorisation ends with the goal.**
> - Everything after is a **separate request**: monitoring the weather is its own standing
>   activity; when the forecast turns, the assistant *offers* a change; accepting it is a new
>   request with its own authorisation. "Make it Sunday" after a completed booking is likewise
>   a new request modifying a completed result.
> - Where the condition cannot be checked yet (date too far out), investigation reports that
>   and the request ends with an offer to monitor and return. Goals do not sit open waiting for
>   the world.
> - The only case an authorisation must outlive a turn is the **uncertain-outcome** case
>   (timeout leaves the fate unknown; goal stays open until resolved through the phases with
>   permission).
>
> **Effect on ratified text:** ADR-0254 §1 gives an authorisation four endings (expiry,
> revoked, superseded, recipient grant lapsed); none is "the goal closed". ADR-0256 rung 3
> sets expiry to the turn-retention window (30 days) regardless of goal state. This ruling adds
> a goal-terminal ending and demotes the retention window to a backstop for a goal that never
> closes. → **short superseding ADR, one edge + one clause, sequenced after ADR-0266**.

And its addendum of the same day, which is what §5 below states:

> When the assistant *offers* a change ("move it to Sunday — that is 135 euros"), the offer
> carries the amount and the user's acceptance is itself the authorisation act (ADR-0254: an
> authority established by answering a question). "A new request each time" is therefore not
> "a separate money prompt each time". The follow-up ADR states this. A *standing* grant
> ("never ask under 20 euros") is a policy, not a request — outside this rule, deferred until a
> real use asks for it; would be its own mechanism (cf. recipient grants).

### The gap this closes, stated as the failure the corpus has today

An `Authorization` leaves `ESTABLISHED` on exactly two edges — `REVOKED` by the user's
withdrawal and `SUPERSEDED` by a later row — and stops being **live** on one further fact, its
own `expires_at` passing (ADR-0254 §1). A recipient grant lapsing takes route (d) away from an
opening-act row at the next dispatch without settling it at all (§1's recheck clause). **None of
the four is the goal closing.** So the corpus as it stands says this: the user asks for a
campsite booking under 150 euros, the booking executes, verification confirms the charge, A10
writes `GoalStatus.ACHIEVED` — and the authority the user granted for **that request** stands
until `proposed_at` plus the deployment's turn-retention window, thirty days by default
(ADR-0256 §1). For thirty days a request the user considers finished carries a live standing
authority, which route (d) would rule `ALLOW` over any later call of that goal and that
declaration whose quote sits under the ceiling.

Nothing in the corpus dispatches such a call today, which is why this is a gap in the **record**
before it is a gap in behaviour: an `ABANDONED` goal has left the open set, so nothing plans for
it (ADR-0250 §12), and every later claim of its cancelled attempt is refused permanently
(ADR-0255 §3, ADR-0261 §5). But the row is what the user reads. `standing_authorizations(goal)`
returns every `ESTABLISHED` row of a goal, live and lapsed (ADR-0254 §11, §16), so a user
opening the listing of a finished booking is shown an authority they hold and can withdraw — a
true rendering of a false state. **The row outliving the request is the defect, and the listing
is where it is visible.**

### The tree, read rather than assumed, at `origin/main` `61f40e9f`

- `core/types.py`'s `GoalStatus` carries **four** members — `ACTIVE`, `ACHIEVED`, `ABANDONED`,
  `BLOCKED` — and no `ANSWERED`; `ANSWERED` is a member of `AttemptOutcome`, which is a
  different vocabulary about a different record.
- **`BLOCKED` is open.** ADR-0250 §1: *"A goal is **open** where its `GoalStatus` is `ACTIVE` or
  `BLOCKED`, and **closed** where it is `ACHIEVED` or `ABANDONED`. No lane reads a third state
  off the status, and **`BLOCKED` is open** because ADR-0249 §4 defines it as 'this objective
  cannot currently be achieved'."*
- `core/types.py`'s `AuthorizationDisposition` carries **six** members and the store's
  `_EDGES` table states ADR-0254 §1's graph once, as data, keyed by the disposition each edge
  leaves.
- `permissions/goal_authorizations.py` holds the store: `_SCHEMA_VERSION` is **1**, the
  `disposition` column is generated from the row's JSON, and one trigger enforces that a
  settlement moves that field and `settled_at` and edits nothing else.
- `wire/envelope.py`'s log entry for ADR-0254's Lane 3 records that **no `Authorization`
  crosses whole and no member of `GoalAuthorizations`, `AuthorizationResolution` or
  `GoalAuthorizationStore` is promoted**; `PROTOCOL_VERSION` reads **43**.
- **`ACHIEVED` has one producer and it is not built.** ADR-0249 §4: *"A10 of #2255 —
  verification against the goal's criteria — is `ACHIEVED`'s only producer."* `ABANDONED`'s one
  producer is `abandon_goal` through `PlanStore.close_goal_abandoned` (ADR-0261 §2).
- **ADR-0262 is in flight on PR #2402 and is depended on nowhere below.**

### What this ADR is not allowed to settle

It adds **one enum member, one store member and no field**. It adds no type, no `Settings`
entry, no surface, no carrier, no Protocol and no error class. It changes nothing about what
route (d) covers, what a coverage member is, what a quote is, what the policy reads at
`decide`, what the audit trail refuses, or what any adapter renders. It writes no `GoalStatus`,
adds no producer of one, and decides nothing about when a goal becomes `ACHIEVED` or `BLOCKED`.
It is not the standing-grant decision the owner's addendum defers, and it does not take that
decision by another route.

## Decision

### 1. A goal that closes ends every authorization of it, and the ending is taken before the status is written

> **Normative — the ending, and the set it is stated over.** **A goal that reaches a closed
> `GoalStatus` — `ACHIEVED` or `ABANDONED`, ADR-0250 §1's own division and no wider set — ends
> every `Authorization` of that goal standing `ESTABLISHED`**, live **and** lapsed, which are
> exactly the rows `GoalAuthorizationStore.standing(goal)` returns (ADR-0254 §16). Each is
> settled **`GOAL_CLOSED`** (§2) at the instant of the closing act. **The ending is stated over
> the set and never over one row**: a goal whose plan reached two declarations holds two rows
> under ADR-0254 §1's per-declaration uniqueness, and an act that ended one would leave the
> other standing under a closed goal.

> **Normative — `BLOCKED` ends nothing, and `ACTIVE` on a reopen ends nothing.** ADR-0250 §1
> rules `BLOCKED` **open**, on ADR-0249 §4's ground that it means *"this objective cannot
> currently be achieved"*: such a goal is still associated to, still planned for and still
> holds attempts, so its request has not ended and neither has its authority. **A lane that
> ended an authorization on a `→ BLOCKED` write has breached this clause**, and a reader who
> takes *terminal* to mean *any status but `ACTIVE`* has read a set this decision does not
> state.

> **Normative — the store member, because the window is the defect and not the guard placed in
> it.** **`GoalAuthorizationStore` gains one member, `end_for_goal(goal: Identifier, /, *, at:
> UtcInstant) -> int`**, which **in one indivisible step** settles every row of that goal
> standing `ESTABLISHED` to `GOAL_CLOSED` with `settled_at` at `at`, and answers **how many it
> moved**. It reads **no clock**, the instant being the caller's, which is ADR-0254 §16's
> discipline for `record` and `settle` alike; it **evaluates no liveness**, ending a lapsed row
> exactly as it ends a live one; it writes **nothing else** — no coverage, no basis, no account,
> no destination set and no `expires_at` is edited, so the store's settlement trigger governs
> this write unchanged; and **a goal the store holds no `ESTABLISHED` row of answers `0`, never
> a raise**, which is the shape `standing` already takes for a goal it does not hold. **A
> second call answers `0`.**

**A member rather than a read and a loop, and the ground is ADR-0261 §2's own.** `standing(goal)`
followed by one `settle` per row would leave a window between the read and the last settlement,
and a row established inside it — by a concurrent turn of the same goal, which ADR-0261 §2 admits
in terms, *"two turns associating concurrently can open two"* — would stand `ESTABLISHED` under a
closed goal for ever, nothing being left to end it. That is the failure this decision exists to
prevent, reached by the mechanism meant to prevent it. It would also need a rule for its own
partial failure, half the rows ended and half not. *"The window is the defect, not the guard
placed in it"* (ADR-0261 §2), one store over.

> **Normative — two writes, not one, and the ending is taken first.** The ending and the
> `GoalStatus` write are **two writes in two stores** and the corpus offers no transaction
> across them — ADR-0255 §6 states the constraint one store over, *"`PlanStore` offers no
> multi-write commit"* — so **no lane states, implements or tests them as one**. `orchestration`
> calls `end_for_goal` **after the closing act's own first read has found the goal open and
> before the closing write**, and on the `ABANDONED` path that closing write is
> `PlanStore.close_goal_abandoned` (ADR-0261 §2), whose three writes stay one indivisible step
> and gain nothing here.

> **Normative — what each failure leaves, and the order is chosen for it.** **Where
> `end_for_goal` raises, the closing act ends there having written nothing at all** — no status,
> no attempt commit — and a retry re-runs the act whole. **Where it succeeds and the status
> write does not, rows stand `GOAL_CLOSED` under a goal that did not close**: the goal keeps
> every attempt it had, its next request finds no standing row and **asks**, and the user's
> answer establishes a fresh row on ADR-0254 §1's path (i). That is the fail-closed direction
> and it is the cost ADR-0254 §1 already accepts for an edited declaration — *"the cost accepted
> in the safe direction"*. **The reverse order is refused**: it would leave an `ESTABLISHED` row
> under a closed goal, which is the state this decision exists to make unreachable, and
> ADR-0261 §2's live-attempt conjunct is stated over `ABANDONED` alone, so an `ACHIEVED` goal may
> still carry a claimable attempt. **No lane adds a sweep, a repair pass, a start-up scan or a
> durable act identity for either residual**, and none reverses the order.

> **Normative — the ending is taken once per act and is not re-taken on ADR-0261 §2's retry.**
> That section retries a `StaleExecutionError` from `close_goal_abandoned` **once**, re-taking
> the act's own first-read decision. **`end_for_goal` is not called a second time**: it is
> already done, a second call would answer `0`, and where the re-read finds the goal closed the
> act answers `ALREADY_CLOSED` with the rows already ended — the same fail-closed residual as
> above and not a second one. **An act that answers `NO_SUCH_GOAL` or `ALREADY_CLOSED` from its
> first read calls `end_for_goal` not at all.**

> **Normative — a `PROPOSED` row of a goal that closes is left exactly as it stands, and this
> decision settles none.** ADR-0254 §1 binds verbatim: *"No sweep, no timer, no reclaim and no
> start-up scan settles it"*, and such a row *"is never live, so it authorises nothing and
> appears in no listing"*. **No edge leaves `PROPOSED` into `GOAL_CLOSED`**, because minting one
> is exactly the sweep that clause refuses, over a row that authorises nothing. The row stays a
> question that was put and was never answered, visible in `recent` and `export` as what it is,
> and settled `EXPIRED` by the first `live_for` read or answer that names it. **A closed goal
> has neither**: it has left the open set, so nothing plans for it (ADR-0250 §1, §12), its
> attempt is terminal and every later claim of that attempt is refused permanently (ADR-0255 §3,
> ADR-0261 §5). And the one turn that can reach such a goal at all **reopens** it first
> (ADR-0250 §13), so an answer that did arrive would arrive on a goal that is open again, which
> is the state the row was proposed for — and ADR-0254 §1's uniqueness still holds, the closure
> having left no `ESTABLISHED` row of that pair. §8 books the decision that would change this.

### 2. `GOAL_CLOSED`: a seventh member, retired, and the ended row never revives

> **Normative.** **`AuthorizationDisposition` gains one member and closes at seven**:
> **`GOAL_CLOSED`**, valued by lower-cased member name like the other six, meaning **this
> authority ended because its goal closed**. The vocabulary is *added to and never renamed*,
> which is ADR-0254 §1's own rule and the licence for this member. **`GOAL_CLOSED` is
> *retired*: no edge leaves it**, so it joins `DECLINED`, `EXPIRED`, `REVOKED` and `SUPERSEDED`
> as the **fifth** member `settle` refuses a move out of, and **it is never live**, §1's
> liveness predicate being stated over `ESTABLISHED` alone.

> **Normative — the graph gains one edge and `settle` admits it, the graph staying stated
> once.** ADR-0254 §1's transition graph gains **`ESTABLISHED → GOAL_CLOSED`** and closes at
> **six** edges. `PROPOSED` and `ESTABLISHED` stay **the two members an edge leaves** and no
> other edge exists. **`settle` admits the new edge like any other** and answers
> `AuthorizationSettlement` unchanged — `SETTLED`, or `NOT_AT_SOURCE` for a row standing
> anywhere but `ESTABLISHED`; **`WOULD_DUPLICATE` is unreachable on it**, that member being
> reachable only on a settlement to `ESTABLISHED`. **A store that refused the member would be a
> second place the vocabulary is decided** (ADR-0250 §9's own sentence, one store over), and a
> `settle` carve-out would need a fifth `AuthorizationSettlement` member to refuse with, which
> §6's writer clause buys at no cost instead.

> **Normative — why a seventh member and not one of the six, stated because ADR-0254 §1 already
> answers the same question once.** **`EXPIRED` is refused** for that section's own reason, read
> one ending over: it *"is the answer a question never got, and re-using it for a lapsed
> authority would make the two indistinguishable in a listing"* — and an authority that ended
> with its goal is a third thing again. **`REVOKED` is refused** because it records the **user's**
> withdrawal, and a surface that showed a system act as one would attribute to the user an act
> they did not take. **`SUPERSEDED` is refused** because it names a later row that replaced this
> one, and there is none. **A `bool`, a flag or a second field on the row is refused** because
> ADR-0254 §1's field list is closed and *"a lane adding a member is changing this decision
> rather than implementing it"*, which ADR-0256 §4 has already declined to reopen once.

> **Normative — a reopened goal is a new attempt and a new act, and the ended row never
> revives.** ADR-0250 §13's reopen writes `GoalStatus.ACTIVE` and opens a new attempt at
> `UNDERSTAND`. **No row settled `GOAL_CLOSED` is restored, re-opened, re-established or read as
> an authority by it**: the member is retired, no edge leaves it, and ADR-0254 §1's posture for
> the same question binds — *"`SUPERSEDED` is retired and no edge leaves it, so nothing
> un-supersedes one"*. The reopened goal's authority is established afresh, by a path-(i)
> proposal the user answers or by a path-(iii) opening act, exactly as a first attempt's is.
> **ADR-0254 §1's uniqueness is satisfied by construction**, the closure having left the goal no
> `ESTABLISHED` row at all.

> **Normative — the ending ends the authority and never the interpretation.** ADR-0250 §13's
> *"Reopening preserves everything the goal holds"* and ADR-0249 §1's append-only chain bind
> entire, so a `USER_STATED` constraint of the goal — the money ceiling among them (ADR-0266 §1)
> — **survives its goal's closure and its reopening unchanged**. What a later request
> re-establishes is the **row**, minted from *"the user's own recorded words of this goal"*
> (ADR-0254 §1), any turn of the goal and not only the latest. **No clause of this decision
> edits, retracts, elides or re-grounds an interpretation revision, and no lane reads a closure
> as licence to ask the user to restate a bound.**

> **Normative — what leaves the listing, stated rather than discovered.** `standing(goal)`
> returns the `ESTABLISHED` rows and nothing else (ADR-0254 §16), so **a row ended `GOAL_CLOSED`
> appears in `standing_authorizations` not at all**, exactly as a revoked or superseded one does
> not. **It is not revocable**, there being nothing left to withdraw and no edge out. **It is
> deleted by nothing**: ADR-0254 §12's no-deletion rule binds entire, `recent` and `export`
> carry it whatever its disposition, and a user reading the record of a finished request still
> finds what they authorised, what it covered and when it ended. **No lane adds a surface, a
> carrier, a member or a second rendering for it**, and the listing renders exactly what
> ADR-0254 §11 fixes.

### 3. The retention window is the backstop, and no instant is moved

> **Normative.** **ADR-0256 §1's rung is the expiry of a row whose goal never closes, and of no
> other.** Every clause of that decision binds unchanged: the rung is taken on ADR-0254 §12's
> paths (i) and (iii) at the instant the row is written, from `Settings.episode_retention` and
> `proposed_at`; `Settings` gains nothing; a correction takes no rung of the ladder; §3's `None`
> case still writes no row at all; and §5's narrowing correction is untouched. **What is
> subordinated is only the claim that the window is the horizon**: a row is now bounded by the
> **earlier** of its own `expires_at` and its goal's closure.

> **Normative — no instant is moved, shortened, recomputed or re-read, and the row ends by a
> disposition alone.** ADR-0254 §12's *"the expiry is taken once, when the row is written, and
> is never recomputed"* binds **entire**. **This decision moves no `expires_at`**, on any path,
> for any reason: `end_for_goal` writes the disposition and its instant and nothing else, so a
> row ended `GOAL_CLOSED` still carries, and `export` still renders, the horizon the act was
> granted under. **A lane that shortened an expiry to express this ending has breached this
> clause**, and would have made the instant the user was shown at the act untrue.

> **Normative — the window keeps the one job it had, and it is the one ADR-0256 §1 argued for.**
> A goal that never closes — the user stops engaging it, no act abandons it, A10 never verifies
> it — has no closing write for §1 to hang an ending on, and its rows lapse on the window
> exactly as ratified. **That is the whole of the backstop**, and ADR-0256 §1's ground for the
> figure is undisturbed: *"an authority takes the window the deployment keeps the record of its
> act for, and never a window minted for it"*. **No lane reads this decision as a reason to
> lengthen, cap, default or re-derive that window**, and ADR-0256 §6's exclusions —
> `RecipientGrant.expires_at` and ADR-0247's configured-provider authority — bind entire and are
> reached by no clause here.

### 4. The uncertain outcome is not an exception, because nothing closes the goal under one

> **Normative.** **This decision adds no exception for an uncertain outcome, and needs none,
> because it writes no `GoalStatus` and adds no producer of one.** While a step of the goal
> stands `INDETERMINATE` the attempt stands `EFFECT_UNRESOLVED`, which ADR-0255 §6 makes
> *"neither a terminal member nor one of the three ADR-0249 §5 derives paused from"*; ADR-0249
> §4 rules that *"An attempt reaching a terminal state **does not** move the goal's status"*;
> and `ACHIEVED` has one producer, **A10's verification against the goal's criteria**, which an
> unresolved effect has not supplied. **So the goal is not closed, no ending fires, and the
> established row stands** — which is the owner's uncertain-outcome case satisfied by the
> ratified route rather than by a clause of this decision.

> **Normative — reconciliation resolves the step and closes nothing.** ADR-0259 §4's pass
> *"writes **no `GoalStatus`**"* and its act 4 returns the attempt to `RUNNING` where no step of
> it stands `INDETERMINATE` or `RUNNING`. **Whether the goal then closes is A10's, by the
> ratified route and by no shortcut this decision offers**: a resolution is a repair of a record
> and is not a verification. **No lane reads a resolved effect, a released attempt or a
> reconciliation pass as a closing act**, and the pass calls `end_for_goal` in no case.

> **Normative — the user's cancellation closes such a goal and ends its authority with it, and
> that is the ruling working rather than an exception to it.** ADR-0261 §2's act closes a goal
> holding an outstanding effect and reports it, answering `ABANDONED_EFFECT_IN_FLIGHT` (§6).
> **The ending fires there like any other `ABANDONED` write** — the user ended the request, and
> an authority for a request the user ended is what this decision exists to retire. **What was
> already dispatched is unaffected**: ADR-0261 §5 binds entire, the effect row is released by
> nothing, and *"no lane reads a reopened goal or a fresh plan as licence to repeat an act"*.

### 5. The offer carries the price, and the acceptance is the authorisation act

> **Normative — an offered change is a path-(i) proposal and the acceptance is its answer.**
> Where the assistant offers a change — *"move it to Sunday — that is 135 euros"* — the offer is
> put as the `CONFIRM` ADR-0254 §1's **path (i)** proposes a row against, and the user's
> acceptance settles that row on §1's **`PROPOSED → ESTABLISHED`** edge. **That is the whole
> mechanism and this decision mints none of it**: no surface, no carrier, no member, no edge and
> no second question. **"A new request each time" is not "a separate money prompt each time"**,
> because the request and the money are one question and the acceptance is one answer.

> **Normative — the amount is rendered by the machinery that already renders it, and a lane adds
> nothing to make that true.** `Confirmation.authorization` carries an
> `AuthorizationProjection` (ADR-0254 §11) whose `coverage` and `expires_at` that section
> requires and whose `quote` ADR-0267 §7 transcribes from the proposed row's `quoted` — the
> governing quote for the request's intended action, read from the goal the row was built from.
> **So the figure the acceptance is taken over is on the screen the user answers**, which is
> ADR-0254 §11's own test — *"A confirmation that establishes a bound without naming it is not a
> confirmation of that bound"* — met by a value the ratified projection already carries. **No
> lane re-selects a quote to render one** (ADR-0267 §7), and **no lane reads this clause as
> widening what a confirmation names.**

**The ruling's two "make it Sunday" cases are one rule read at two instants, and ADR-0266 §7 is
reached and superseded in nothing.** That section's worked case — *"'Make it Sunday' replans and
the re-quote is `135`: that quote governs, `135 ≤ 150`, and **still no question**"* — runs at
phase 3 of a **live** goal, before the booking executes; the row stands `ESTABLISHED`, route (d)
covers the re-quoted call, and every word of it is true after this decision. The owner's
*"'Make it Sunday' after a completed booking is likewise a new request modifying a completed
result"* is the **other** instant: the goal closed, §1 ended the row, and the change is offered
and accepted under §5. The two never meet, because a goal is closed or it is not, and what tells
them apart is the goal's status and not the words the user used.

### 6. Writer clauses, and what this decision leaves exactly as it stands

> **Normative — one writer, one call site.** **`orchestration` calls `end_for_goal` and nothing
> else does**, which is ADR-0254 §15's clause reaching one member — an `Authorization` is
> *"written and settled by `orchestration` and by nothing else"*. **No store, no `ActionPolicy`,
> no `AuditTrail`, no interface adapter, no reader, no tool and no model output calls it, and no
> model output decides that a goal has closed.** `GoalAuthorizations` and
> `AuthorizationResolution` gain **nothing**: the policy's face still carries `live_for` alone
> and the trail's `resolve` alone, so neither can reach this member (ADR-0254 §16's three faces,
> unchanged).

> **Normative — `GOAL_CLOSED` is written through `end_for_goal` alone.** **No act settles a
> single row to it through `settle`**, though §2 leaves that move admissible: a row ended on its
> own would assert that a goal closed when none did, and the fact this member records is a fact
> about the **goal**. **A lane that wrote `GOAL_CLOSED` from anywhere but the closing act has
> breached this clause.**

> **Normative — §13's recheck and §7's trail invariant bind entire, and this decision adds no
> residual to either.** ADR-0254 §7's route-(d) refusal reads the resolved row's `disposition`
> and requires **`ESTABLISHED`** — *"the existence, the kind, the unrevoked, the unsuperseded and
> the answered check at once, since every other disposition is retired and none of them is
> live"* — and that reason is true of `GOAL_CLOSED` as it is of the other four, so the check is
> unchanged and needs no conjunct. **A goal closing between `live_for` and `AuditTrail.record`
> refuses the write**, exactly as ADR-0254 §20's arm 4 records for a revocation landing in the
> same window. **A goal closing between the ruling and a claim already taken is ADR-0254 §13's
> stated residual and §19's A9 booking, unnarrowed and unwidened**: a settlement is a settlement,
> and this decision claims nothing stronger about its own than that section claims about a
> revocation.

> **Normative — what is untouched, named so a lane cannot read silence as licence.**
> `Authorization`'s **field list stays closed** and gains nothing. `CoverageMember`,
> `ValueBound`, `BoundedArgument`, `ActionQuote` and every reading over them are untouched, and
> **condition 6 is not reached in any limb** (ADR-0266 §7, ADR-0267). `AuthorizationSettlement`
> stays closed at four, `AuthorizationOrigin` at two, `AuthorizationProjection`,
> `AuthorizationView` and `CoverageView` gain no member, and `core/errors.py` gains no class.
> `core.config.Settings` gains **nothing at all**. `GoalStatus`, `AttemptState`,
> `AttemptOutcome`, `GoalAbandonment` and `AttemptPhase` gain **no member**, and no writer of any
> of them is added, removed or re-attributed.

### 7. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a reader holding
only that ADR now act differently, or read one of its clauses more widely than it now holds? For
each limb below the answer is yes, and the sentence that becomes false or over-wide is named.
**Five places, in two documents.**

1. **ADR-0254 §1's `AuthorizationDisposition` clause**, in its closure and its retired
   enumeration: *"closed at exactly **six** members"* becomes seven, gaining `GOAL_CLOSED`, and
   *"`DECLINED`, `EXPIRED`, `REVOKED` and `SUPERSEDED` are *retired*: no edge leaves them"*
   enumerates four where there are now five. A reader holding only §1 authors an enumeration
   that cannot spell the ending an authority now has, and a `settle` that refuses a move out of
   four dispositions where a fifth is retired. **The rule that licenses the addition is that
   section's own** — *"The vocabulary is added to and never renamed"* — so nothing is renamed and
   no member's meaning moves.
2. **ADR-0254 §1's transition graph**, in its edge count alone: *"stated whole, and there are
   exactly **five** edges"* becomes six, the sixth being `ESTABLISHED → GOAL_CLOSED`. **Its two
   other assertions stand verbatim and are relied on**: *"`PROPOSED` and `ESTABLISHED` are the
   two members an edge leaves"*, which the new edge satisfies, and *"no other edge exists"*, read
   over the six. **`settle`'s own clause stands verbatim but for the count** — it still *"moves a
   row along one of §1's edges under compare-and-swap and refuses every move that is not an
   edge"*, and `AuthorizationSettlement` is unmoved at four members. A reader holding only §1
   ships a graph an ending cannot be expressed in.
3. **ADR-0254 §16's store roster**, in the signature count alone: the **eight** signatures that
   section states *"in full, because a roster of names is not a contract"* become **nine**,
   gaining `end_for_goal(goal, /, *, at) -> int`. `GoalAuthorizations` and
   `AuthorizationResolution` gain nothing, so **§16's three-faces construction stands entire**,
   as do its detached-snapshot rule, its clock disciplines — the new member evaluates no liveness
   and reads no clock — its `standing` clause, its data-rights clause and its `PROTOCOL_VERSION`
   clause. **§16's `core/types.py` and `core/errors.py` rosters take no scope**: this decision
   adds no type, no field and no class, so the counts ADR-0266 §9 and ADR-0267 §9 left them at
   are unmoved. A reader holding only §16 implements a store whose contract has no ending on it.
4. **ADR-0254 §20, in two limbs and in an enumeration each time.** **Lane 1's *"The **eight**
   store signatures"*** goes with §16's roster above. **And arms 37 and 55, each in its
   retired-disposition enumeration and its edge count alone** — arm 37's *"Each of the five edges
   succeeds under compare-and-swap; every other move is refused, with one test per retired
   disposition"* and arm 55's *"Each of the five edges from its own source → `SETTLED`; … one
   test per retired disposition"* — which now enumerate six edges and five retired dispositions.
   **Every assertion of both stands verbatim**, their subject being `settle`, which still refuses
   every move that is not an edge and still cannot leave a retired member; what grows is the
   number of cases each arm is stated over. **Every other arm of §20 is untouched**, arm 4's
   revocation-between-`live_for`-and-`record` case conspicuously so, which §6 above reads as the
   shape of this ending's own race rather than as a case that moves.
5. **ADR-0256 §1's bound clause, in the direction of the bound alone**, and with it that
   decision's title: *"**A row written on this rung is bounded by the turn-retention window in
   force at its own write, measured from `proposed_at`, and by nothing longer**"* stays true as an
   **upper** bound and stops being the horizon — such a row now ends at the earlier of that
   instant and its goal's closure. A reader holding only ADR-0256 reads the window as when the
   authority ends and would report a live authority over a finished request for the rest of it.
   **Every other clause of ADR-0256 binds entire and several are what this rests on**: §1's rung
   and its `proposed_at`-only read, its no-new-reader rule and its illustrative list of rows that
   outlive an act's record; §2's `Settings`-gains-nothing, read-once and fail-closed arithmetic;
   §3's `None` case, which writes no row at all and is untouched; §4's rendering and its refusal
   of a `source` member; §5's narrowing correction; and **§6 entire**, whose *"No row is moved,
   shortened or settled by anything that happens to the act's own record"* is stated over the
   **act's record** and is reached by no clause of this decision — what ends a row here is the
   **goal's** status, which is neither an episode nor a conversation. §§7-11 stand as they are.

**Reached and superseded in nothing, recorded because a reader would otherwise look for a
scope.** **ADR-0266 §7's worked case** is stated at phase 3 of a live goal and every word of it
survives (§5 above). **ADR-0267 §7** is relied on and unmoved, `quoted` being provenance no
comparison reads. **ADR-0261 §2 and §5** bind entire: this decision adds no conjunct to
`close_goal_abandoned`, `set_goal_status` or `open_attempt`, and moves no attempt and no step.
**ADR-0250 §1's division is read and not changed**, and §13's reopen is untouched. **ADR-0249
§4** is quoted rather than narrowed: `ACHIEVED` and `BLOCKED` gain no producer here.

### 8. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward
> any of them.

- **A standing grant across requests** — *"never ask under 20 euros"*. The owner's addendum rules
  it a **policy and not a request**, outside this rule and deferred. It would be its own
  mechanism, and the shape it would take is **ADR-0193 §1's**: a durable, dated, revocable record
  of its own with its own store, its own covering rule and its own ceiling on how many may stand
  — not a member, a field or a wider reading of `Authorization`, which is keyed on one goal and
  which §2 above has just made end with one. Fired by a real use asking for it.
- **Monitoring as a standing activity.** The ruling makes it *"its own standing activity"* and
  this decision gives it no mechanism, no record and no authority: a goal that ends with an offer
  to monitor ends, and what watches the world afterwards is decided elsewhere. Fired by the
  decision that lands it.
- **What *"make it Sunday"* costs when the booking must be modified.** **ADR-0265's identity rule
  stands entire** — an intended action's identity is minted once and links to the goal elements it
  serves — and the money is asked again through §5's offer, whose acceptance is the answer.
  Whether modifying a completed booking is one intended action or two is that decision's question
  and not this one's.
- **An ending for a `PROPOSED` row of a closed goal.** §1 leaves it exactly as ADR-0254 §1
  leaves it and mints no edge. Fired by a decision that gives a closed goal an answerable
  confirmation — which would need a route from a turn to a closed goal that does not reopen it,
  and ADR-0250 §13 offers none today.
- **`GoalStatus.ACHIEVED`'s producer (A10) and `BLOCKED`'s (A3).** ADR-0249 §4 reserves both and
  ADR-0254 §19 books both; this decision writes neither and states only what a closing write
  additionally owes.
- **Retention for this store beyond `clear`.** ADR-0254 §19's entry, untouched: a `GOAL_CLOSED`
  row is deleted by nothing, exactly as every other row is.

### 9. The lane cut, the wire, the stored shape, and the arms this decision owes

> **Normative — one lane, and the ground is that the member has exactly one caller.**
> **`core/types.py`'s `GOAL_CLOSED`, `core/protocols.py`'s `end_for_goal`, the
> `GoalAuthorizationStore` conformance suite's arms for both, the canonical fake in
> `ai_assistant.testing`, `SqliteGoalAuthorizationStore`'s implementation in `permissions/`, and
> `orchestration`'s one call site on the `ABANDONED` path are one change.** ADR-0137 §2's
> construction is what makes it one — the contract rides with the primary production consumer
> whose demands shape it — and the demand here is total: a lane landing the member without its
> caller leaves a tree in which an authority never ends, which is the whole decision unlanded.
> **It is a BREAKING contract change under golden rule 5 and is flagged as one**, and this ADR
> merges, ratified, before it (ADR-0015).

> **Normative — the `ACHIEVED` call site is A10's and is not this lane's.** `ACHIEVED` has no
> producer in the tree (ADR-0249 §4), so **the lane above wires `end_for_goal` on the
> `ABANDONED` path alone**, which is the one closing write that exists. **A10's lane calls it
> before its own `set_goal_status(…, ACHIEVED)` write, on §1's order and with §1's residual**,
> and **no lane ships a producer of a closed `GoalStatus` without it**.

> **Normative — `PROTOCOL_VERSION` does not move, and the ground is read off the tree rather
> than assumed.** ADR-0124 §9's test is *"a change to a wire-carried `core` type that makes a
> value one peer emits invalid for the other"*, and **no wire-carried value changes**: ADR-0254
> §16 rules that *"**No `Authorization` crosses whole and no member of `GoalAuthorizations`,
> `AuthorizationResolution` or `GoalAuthorizationStore` is promoted**"*, the four carriages that
> do cross are projections, `AuthorizationView` carries `live`, a `bool`, and **not** a
> disposition, and `AuthorizationSettlement` — which does cross, through `revoke_authorization`
> — gains no member. **`end_for_goal` is promoted by nothing.** **A lane that finds the tree
> disagrees takes the bump and records the correction in `wire/envelope.py`'s log**, rather than
> reading this clause as permission to skip one.

> **Normative — the authorization store's `schema_version` moves by exactly one and no migration
> is owed.** A file written after this decision may carry a `disposition` an earlier reader
> refuses, which is ADR-0039 §10's mechanism as ADR-0261 §10 applies it one store over. **No row
> is rewritten, re-dispositioned or back-filled**: no row predating this decision can be
> `GOAL_CLOSED`, so the migration is the version marker and nothing else. The tree holds **1**
> as a dated observation at `61f40e9f`. **No compatibility shim, lenient decode or
> tolerated-unknown entry is added.**

> **Normative — the arms the lane owes, and they are six.**
>
> 1. **The ending over the set.** A goal holding established rows for two declarations, one live
>    and one lapsed, plus a `PROPOSED` row and a row already `SUPERSEDED`: `end_for_goal` answers
>    **2**, both established rows stand `GOAL_CLOSED`, and the `PROPOSED` and `SUPERSEDED` rows
>    are **byte-identical** to what they were. A second call answers **0**. A goal the store holds
>    no row of answers **0** and does not raise.
> 2. **Indivisibility and the closed window.** A row recorded and settled `ESTABLISHED`
>    concurrently with `end_for_goal` leaves the store in one of exactly two states — the row
>    ended, or the row established and the call's answer not counting it — and **never** a state
>    in which some established rows of the goal are ended and others stand with the call
>    reporting success.
> 3. **The graph, `settle` and the retired member.** `ESTABLISHED → GOAL_CLOSED` through `settle`
>    → `SETTLED`; the same call repeated → `NOT_AT_SOURCE`; **every** move out of `GOAL_CLOSED`
>    → `NOT_AT_SOURCE`, one test per target; `PROPOSED → GOAL_CLOSED` → `NOT_AT_SOURCE`. A
>    `GOAL_CLOSED` row is **never** live, is absent from `standing`, and is present in `recent`
>    and in `export` carrying its coverage, its basis and its unmoved `expires_at`.
> 4. **The closing act, in order.** `abandon_goal` on a goal holding two established rows ends
>    both and **then** closes the goal; the act's answer is `ABANDONED` or
>    `ABANDONED_EFFECT_IN_FLIGHT` exactly as ADR-0261 §6 fixes it; an act answering
>    `NO_SUCH_GOAL` or `ALREADY_CLOSED` from its first read ends **nothing**; and a
>    `StaleExecutionError` retry that then finds the goal closed calls `end_for_goal` **once** in
>    the whole act.
> 5. **`BLOCKED` and the reopen.** `set_goal_status(…, BLOCKED)` ends **no** row and the goal's
>    rows still cover a later request; ADR-0250 §13's reopen writes `ACTIVE`, ends nothing,
>    revives nothing, and the goal's `USER_STATED` constraints are **unchanged** across the
>    closure and the reopening.
> 6. **The trail and the recheck.** A route-(d) `ALLOW` whose row is ended `GOAL_CLOSED` between
>    `live_for` and `AuditTrail.record` is **refused** on ADR-0254 §7's disposition check, with no
>    conjunct added; and `decide` over a goal whose rows are all `GOAL_CLOSED` reaches route (d)
>    in no case, `live_for` answering `None`.

### 10. This ADR classified, marked, and how it is ratified

**A reader acts differently, so this is a decision and not a clarification.** A reader holding
the corpus without it ships an authority that outlives the request it was granted for by up to a
deployment's whole retention window, and a listing that offers the user a live authority over a
finished booking. **It is a partial supersession of exactly two documents** (ADR-0070 §3) —
ADR-0254 in four scopes and ADR-0256 in one — and the `Status` line of each names its scopes
**without an `ADR-NNNN` token inside the parentheses**, so ADR-0070 §4's extraction invariant
holds. **The records land in the same change as this document** (ADR-0082 §7), and nothing else
in either is edited — no Decision text is rewritten, which ADR-0070 §1 forbids.

**This ADR is marked** under ADR-0089 as ADR-0257 §1 widens the token: every obligation is a
normative blockquote at column 0 stating its own scope, unmarked text beside a mark supplies no
obligation of its own but settles what a mark means (§3), and quoted marks appear inside
quotation marks in running prose.

**It is a contract-surface change** — `core/types.py`'s `AuthorizationDisposition` gains a
member and **`core/protocols.py`'s `GoalAuthorizationStore` gains one** — so it owes **both**
review lenses on one tree, which ADR-0015 §1 makes true of a prose-only PR. **No new Protocol is
added, so no triad is owed**: the member lands on a Protocol whose conformance suite and
canonical fake already exist and each gains its arms. **It merges as its own PR, ratified,
before anything implements against it** (golden rule 5); §9's lane is briefed after it merges,
and the ratification flip is one line and no other byte (ADR-0165).

## Consequences

**What becomes possible.** An authorisation can be said to be *for a request*, which is the
sentence the owner's ruling is written in and which the corpus could not previously express: the
row comes into being when the user answers, covers every call of that request the quote sits
under, and ends in the write that finishes the request. A user opening the listing of a finished
booking sees no authority, because they hold none. And the campsite walkthrough M33 runs becomes
checkable end to end — book, verify, close, and the ceiling is gone — rather than ending with a
standing authority nobody intended and nothing retires.

**What becomes harder, and each is a question asked rather than a call authorised.** Every
request after a goal closes asks, including one the user experiences as a small amendment:
*"make it Sunday"* the day after a confirmed booking is a fresh confirmation, and the only thing
that stops it being a fresh **money** question is §5's offer carrying the figure. A goal closed
by mistake cannot have its authority restored — the member is retired and the repair is the
user's own answer, which is the fail-closed direction and the same one ADR-0254 §1 takes for
supersession. And a deployment that closes goals eagerly asks more often than one that leaves
them `ACTIVE`, which makes A10's verification rule a lever on how often the user is interrupted —
a coupling worth watching and one nothing here can hide.

**What is disclosed rather than closed.** The ending is **two writes**, and a failure between
them leaves rows ended under an open goal; the cost is a question and there is no sweep to
reclaim it (§1). A call already claimed when its goal closes is ADR-0254 §13's residual window
unchanged, and A9's to close. And a `PROPOSED` row of a closed goal stays `PROPOSED` for ever
unless something reads it — a state ADR-0254 §1 already admits and this decision declines to
sweep, on that section's own grounds.

**These are the cases that would falsify the design.** A workflow in which the user genuinely
expects one authority to span several requests — a trip planned as five bookings under one
budget — which the goal-keyed row would make five questions, and which the standing grant §8
defers is the answer to rather than this ending being wrong. A10 turning out to close goals far
later than the user considers the request finished, so the authority outlives it anyway and the
ending buys nothing. And an offer flow in which the figure is not available when the offer is
composed, so §5's *"not a separate money prompt"* fails not as a rule but for want of a quote —
the practical falsifier by a distance, and ADR-0267 §6's freshness disclosure is where it is
already visible.

## Alternatives considered

**Shorten the row's `expires_at` when the goal closes.** Rejected. ADR-0254 §12's *"taken once,
when the row is written, and is never recomputed"* is what makes the instant the user was shown
at the act true afterwards, and an ending expressed by moving it would make the record say the
authority lapsed on a horizon nobody stated. A disposition says what happened; an edited instant
says something that did not.

**Reuse `EXPIRED`, or `REVOKED`.** Rejected on ADR-0254 §1's own reasoning, read one ending over:
re-using a member makes two different facts indistinguishable in a record whose whole purpose is
to say what the user authorised and what became of it. `REVOKED` would be worse than
indistinguishable — it would attribute to the user an act they did not take.

**Make liveness depend on the goal's status, with no new member.** Rejected. `live_for` would
have to read the goal, which puts a `PlanStore` read on `ActionPolicy.decide`'s path across a
subsystem boundary — the shape ADR-0256 §6 declines for the closely related question of an act's
own record, *"machinery ADR-0254 §16's roster does not contain"* — and it would leave the row
saying `ESTABLISHED`, so the listing would still show an authority the policy would refuse.

**Read `standing(goal)` and settle each row, adding no store member.** Rejected for the window
and the partial failure (§1), and because the loop's own residual — some rows ended, some not —
would need a rule this decision would then have to state. One call has neither.

**Write the status first and end the rows after.** Rejected: its residual is an `ESTABLISHED` row
under a closed goal, which is the exact state this decision exists to make unreachable, and
ADR-0261 §2's live-attempt conjunct is stated over `ABANDONED` alone, so an `ACHIEVED` goal may
still carry a claimable attempt for it to cover.

**End the goal's `PROPOSED` rows too, on a second edge.** Rejected as the sweep ADR-0254 §1
refuses in terms, over a row that is never live and authorises nothing, and because it would make
one member record two facts — an authority that ended and a question that was abandoned — where
the section's reason for minting a new member in the first place is that a record should not.
