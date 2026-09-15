# 268. An authorization ends when its goal closes, the retention window is only the
backstop, and an offered change carries the price its acceptance authorises

- Status: Proposed
- **Partially supersedes** [ADR-0254](0254-phase-4-validates-the-plan-in-code-and-route-d-authorises-a-concrete-call-against-fixed-values-and-permitted-ranges-from-recorded-acts.md)
  — **four scopes.** **§1's `AuthorizationDisposition` clause**, in its closure and its retired
  enumeration: *"closed at exactly **six** members"* becomes **seven**, gaining
  **`GOAL_CLOSED`** — valued by lower-cased member name, meaning *this row was ended by a
  closing act of its goal*, and **retired**, no edge leaving it — and *"`DECLINED`, `EXPIRED`, `REVOKED` and
  `SUPERSEDED` are retired: no edge leaves them"* enumerates four where there are now five. §1's
  own *"The vocabulary is added to and never renamed"* is the licence and is unmoved. **§1's
  transition graph, in its edge count, and §1's `PROPOSED`-row clause, in the settlers it
  enumerates.** *"stated whole, and there are exactly **five** edges"* becomes **seven**, the
  new ones being `PROPOSED → GOAL_CLOSED` and `ESTABLISHED → GOAL_CLOSED`, both taken by the act
  that closes the goal; its two other assertions stand verbatim — `PROPOSED` and `ESTABLISHED`
  stay the two members an edge leaves, and no other edge exists — and `settle`'s own clause
  stands but for the count, `AuthorizationSettlement` unmoved at four members and
  `WOULD_DUPLICATE` unreachable on either new edge. And §1's clause that an expired proposal is
  settled *"by the **first operation that reads it**, and there are exactly **two** — a
  `live_for` read, and the answer that names it"* gains a **third** settler in the closing act's
  `end_for_goal`, which settles it `GOAL_CLOSED` rather than `EXPIRED`; **that clause's negative
  limb is untouched and is what makes the addition admissible** — *"**No sweep, no timer, no
  reclaim and no start-up scan** settles it"* stays true word for word, the closing act being
  none of the four but a user act's own write — and its *"a `PROPOSED` row neither operation
  reads again stays `PROPOSED`"* is narrowed to a goal that does not close. §1's field list, its
  three write paths, its one-`ESTABLISHED`-row uniqueness rule, its conditional supersession and
  its liveness predicate are untouched. **§16's store roster, in the signature count, and §16's
  `InvalidAuthorizationError` clause, in its enumeration of refused writes.** The **eight**
  signatures stated *"in full, because a roster of names is not a contract"* become **ten**,
  gaining `end_for_goal(goal, /, *, at, goal_version) -> int` — which in one indivisible step
  settles every row of a goal standing `PROPOSED` or `ESTABLISHED` to `GOAL_CLOSED`, fences the
  goal in this store at that version, and answers how many rows it moved, reading no clock,
  evaluating no liveness and doing none of it where the store's record already stands
  higher — and `clear_closure(goal, /, *, goal_version) -> bool`, which lifts that fence where
  the record stands at or below the version passed, removes no record and settles nothing.
  And the
  list of writes `record` refuses gains one further entry, a row whose `goal` the store holds
  fenced, refused in the same indivisible step as the write; **that class is reused and
  no class is minted**, `core/errors.py` and `AuthorizationError` untouched, and `settle` gains
  no conjunct, a settlement naming a row the ending settled answering `NOT_AT_SOURCE` on the
  ratified graph. `GoalAuthorizations` and `AuthorizationResolution` gain **nothing**, so §16's
  three-faces construction stands entire, as do its detached-snapshot rule, its clock
  disciplines, its `standing` clause, its `settle`-outcomes clause, its data-rights, `export`
  and `clear` clauses and its `PROTOCOL_VERSION` clause — which this decision does not fire, no
  `Authorization` crossing whole and neither new member being promoted. §16's `core/types.py`,
  `core/errors.py` and `PermissionDecision` rosters take **no scope**: no type, no field and no
  error class is added. **And §20, in two limbs**: Lane 1's *"The **eight** store signatures"*,
  which goes with §16's roster and becomes ten; and **arms 37 and 55**, each in its edge count
  and its retired-disposition enumeration, which now run over seven edges and five retired
  dispositions, **and arm 37 in one further limb**, its *"a row read after its `expires_at`
  while still `PROPOSED` is settled `EXPIRED` by a `live_for` read and by the answer that names
  it, **and by no other operation**"*, whose last limb is false of the closing act. Every other
  assertion of both stands verbatim, their subject being `settle`; every other arm is untouched,
  arm 4's revocation-between-`live_for`-and-`record` case conspicuously so; and §20's lane cut
  and its wire clause bind entire. **§§2-15 and §§17-22 stand as they are, but for the limbs of
  §1, §16 and §20 named above**, and several are what the superseding decision rests on: §7's
  route-(d) invariant needs no conjunct, its own ground — *"every other disposition is retired
  and none of them is live"* — being true of the new member; §11's listing, announcement,
  projection and revocation surfaces gain nothing, and a row ended under the new member simply
  leaves the listing as a revoked one does; §12's expiry-taken-once and no-deletion rules bind
  entire and **no instant is moved**; §13's recheck at `decide` and its stated residual are
  unnarrowed; §15's writer clauses reach both new members unchanged; and §19's entries are each
  untouched
- **Partially supersedes** [ADR-0256](0256-an-authorization-with-no-stated-instant-and-no-goal-deadline-takes-the-retention-window-its-acts-own-record-lives-under.md)
  — **one scope. §1's bound clause, in the direction of the bound alone**, and with it that
  decision's title: *"**A row written on this rung is bounded by the turn-retention window in
  force at its own write, measured from `proposed_at`, and by nothing longer**"* stays true as an
  **upper** bound and stops being the horizon — such a row is ended by a closing act of its goal
  where one reaches it, and lapses on that instant where none does. A reader holding only that
  decision reads the window as when the authority ends, and would report a live authority over a
  finished request for the rest of it. **Every other clause binds entire and several are what
  this rests on**: §1's rung, its `proposed_at`-only read, its no-new-reader rule and its
  illustrative list of rows that outlive an act's record; §2's `Settings`-gains-nothing,
  read-once and fail-closed arithmetic; §3's keep-turns-forever case, which writes no row at all;
  §4's rendering and its refusal of a `source` member; §5's narrowing correction; and **§6
  entire**, whose *"No row is moved, shortened or settled by anything that happens to the act's
  own record"* is stated over the **act's record** and is reached by no clause of this decision —
  what ends a row here is a **closing act of its goal**, which is neither an episode nor a conversation.
  §§7-11 stand as they are.
- **Partially supersedes** [ADR-0250](0250-a-turn-finds-its-goal-before-it-plans-and-a-material-ambiguity-becomes-one-durable-question-bound-to-that-goal.md)
  — **one scope.** **§13's enumeration of what a reopen does, in that enumeration alone**:
  *"Reopening writes `GoalStatus.ACTIVE` through `PlanStore.set_goal_status` (§9), opens a new
  attempt (§12) and engages the goal (§1)"* gains a **fourth and a fifth act, taken in order
  immediately after a successful `ACTIVE` write** — `GoalAuthorizationStore.end_for_goal` over
  that goal, ending any row a closure never reached, and then
  `GoalAuthorizationStore.clear_closure` over it, lifting the fence — both carrying that
  write's own `expected_version`. **Without the fifth** the goal stays fenced against every new
  authorization and the reopened request can establish none, every call of it asking for ever;
  **without the fourth** a database written before this decision reopens with its old rows still
  standing `ESTABLISHED`, and they cover the new request. **The ordering is the enumeration's
  own**, the `ACTIVE` write's compare-and-swap being what makes exactly one of two racing
  reopens the one that takes the pair, so a stale reopen retires no row the winner established.
  A reader holding only §13 ships a reopen that cannot authorise anything. **That enumeration alone and nothing else in §13**: its *"Reopening preserves
  everything the goal holds"* clause binds **entire** and is what the superseding decision rests
  on — the interpretation chain, the `interpretation_elided` count, the `conversation_id`, the
  earlier attempts and the no-replay rule are each untouched, an authorization being none of
  them — and so do §13's `EngagementDisposition.REOPENED` case, its explicit-reference rule, its
  no-identifier rule, its `conversation_id`-provenance clause, its candidate clause and its
  resolves-against-the-`PlanStore` clause. **§§1-12 and §§14-21 stand entire**, and two are read
  rather than changed: §1's open/closed division, which the superseding decision takes as its
  trigger, and §12's abandonment sequence, which gains nothing there
- Date: 2026-09-15

## Context

### Where this comes from

The owner's ruling on #2255 of 2026-09-14, quoted rather than summarised, because every clause below
is stated against it:

> **an authorisation lasts for its request, and a request ends when the action is done.**
>
> - A request is judged against the world as it is now. Forecast dry → booking executes →
>   verification confirms → goal complete → **the authorisation ends with the goal.**
> - Everything after is a **separate request**: monitoring the weather is its own standing activity;
>   when the forecast turns, the assistant *offers* a change; accepting it is a new request with its
>   own authorisation. "Make it Sunday" after a completed booking is likewise a new request
>   modifying a completed result.
> - Where the condition cannot be checked yet (date too far out), investigation reports that and the
>   request ends with an offer to monitor and return. Goals do not sit open waiting for the world.
> - The only case an authorisation must outlive a turn is the **uncertain-outcome** case (timeout
>   leaves the fate unknown; goal stays open until resolved through the phases with permission).
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

An `Authorization` leaves `ESTABLISHED` on exactly two edges — `REVOKED` by the user's withdrawal
and `SUPERSEDED` by a later row — and stops being **live** on one further fact, its own `expires_at`
passing (ADR-0254 §1). A recipient grant lapsing takes route (d) away from an opening-act row at the
next dispatch without settling it at all (§1's recheck clause). **None of the four is the goal
closing.** So the corpus as it stands says this: the user asks for a campsite booking under 150
euros, the booking executes, verification confirms the charge, A10 writes `GoalStatus.ACHIEVED` —
and the authority the user granted for **that request** stands until `proposed_at` plus the
deployment's turn-retention window, thirty days by default (ADR-0256 §1). For thirty days a request
the user considers finished carries a live standing authority, which route (d) would rule `ALLOW`
over any later call of that goal and that declaration whose quote sits under the ceiling.

Nothing in the corpus dispatches such a call today, which is why this is a gap in the **record**
before it is a gap in behaviour: an `ABANDONED` goal has left the open set, so nothing plans for it
(ADR-0250 §12), and every later claim of its cancelled attempt is refused permanently (ADR-0255 §3,
ADR-0261 §5). But the row is what the user reads. `standing_authorizations(goal)` returns every
`ESTABLISHED` row of a goal, live and lapsed (ADR-0254 §11, §16), so a user opening the listing of a
finished booking is shown an authority they hold and can withdraw — a true rendering of a false
state. **The row outliving the request is the defect, and the listing is where it is visible.**

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

### What this ADR is not allowed to settle

It adds **one enum member, two store members, one further refusal on a member that exists, and no
field**. It adds no type, no `Settings` entry, no surface, no carrier, no Protocol and no error
class. It changes nothing about what route (d) covers, what a coverage member is, what a quote is,
what the policy reads at `decide`, what the audit trail refuses, or what any adapter renders. It
writes no `GoalStatus`, adds no producer of one, and decides nothing about when a goal becomes
`ACHIEVED` or `BLOCKED`. It is not the standing-grant decision the owner's addendum defers, and it
does not take that decision by another route.

## Decision

### 1. A goal that closes ends every authorization of it and admits no more, in one step

> **Normative — the ending, the set it is stated over, and the trigger.** **A *closing act* of a goal
> — an act whose own write names a closed `GoalStatus`, `ACHIEVED` or `ABANDONED`, ADR-0250 §1's own
> division and no wider set — ends every `Authorization` of that goal standing `PROPOSED` or
> `ESTABLISHED`**, a live row and a lapsed one alike, each settled **`GOAL_CLOSED`** (§2) at the
> instant of the act; **and in the same indivisible step the goal is fenced in the authorization
> store, so that no row of it comes into being while that fence stands.** **The trigger is the act and
> not the status the goal ends up holding**, which is what makes the ending total: the ending is taken
> **before** the status write (below), so a closing write that then fails leaves rows this decision
> has ended under a goal that is still open — stated here, truthful under §2's meaning, and the reason
> §3 states the backstop over the rows no closing act ends rather than over the goals that never
> close. **An act is a closing act by the write it takes and not by that write landing**, which is why
> the definition above is stated over what the act writes: defined over the status the goal ends up
> holding it would make §2's member untruthful on exactly the path this clause states, and the ending
> would have to follow the status write — the race the order below exists to close. **The ending is
> stated over an attempt the store accepts, and an overtaken attempt closes nothing and so ends
> nothing**: an attempt whose `goal_version` the store's record already stands above ends no row and
> fences nothing (the watermark, below), and the universal holds rather than admitting an exception:
> **a record standing above that version means some act read the goal above it**, so the goal itself
> has advanced past the version this attempt carries and **its own closing write is refused stale** by
> ADR-0250 §9's compare-and-swap. **The implication runs one way and that is the way that matters**: a
> refused ending guarantees a refused closing write, while a closing write refused on its own — the
> goal advanced by a write that fenced nothing — is the ordinary stale loss the retry clause below
> governs. **Nothing is lost**: ADR-0261 §2's re-read and retry takes a fresh attempt with a fresh
> ending at the version it then finds, and the rows the overtaken attempt would have ended are of a
> request established after its read, which it never had an authority over. **The ending is stated
> over the set and never over one row**: a goal whose plan reached two declarations holds two rows
> under ADR-0254 §1's per-declaration uniqueness, and an act that ended one would leave the other
> standing under a closed goal.

> **Normative — `BLOCKED` ends nothing, and this decision reaches no other status write.** ADR-0250 §1
> rules `BLOCKED` **open**, on ADR-0249 §4's ground that it means *"this objective cannot currently be
> achieved"*: such a goal is still associated to, still planned for and still holds attempts, so its
> request has not ended and neither has its authority. **A lane that ended an authorization on a `→
> BLOCKED` write has breached this clause**, and a reader who takes *terminal* to mean *any status but
> `ACTIVE`* has read a set this decision does not state.

> **Normative — the two store members, in full, because a roster of names is not a contract.**
> **`GoalAuthorizationStore` gains exactly two members and no third.**
>
> - **`end_for_goal(goal: Identifier, /, *, at: UtcInstant, goal_version: int) -> int`** — **in one
>   indivisible step** settles every row of that goal standing `PROPOSED` or `ESTABLISHED` to
>   `GOAL_CLOSED` with `settled_at` at `at`, **raises the goal's closure record to `goal_version`
>   with the fence standing**, and answers **how many rows it moved**. It reads **no clock**, the
>   instant being the caller's, which is ADR-0254 §16's discipline for `record` and `settle` alike;
>   it **evaluates no liveness**, ending a lapsed row exactly as it ends a live one; and it edits
>   **nothing else** on any row, so the store's settlement trigger governs this write unchanged.
>   **Where the record already stands at a version *above* `goal_version` it moves no row, writes
>   nothing and answers `0`** — the stale-call rule below. **A goal the store holds no row of
>   answers `0`** and is fenced all the same, which is the shape `standing` already takes for a goal
>   it does not hold; and a call at or above a standing record finds no row left to move and answers
>   `0` too.
> - **`clear_closure(goal: Identifier, /, *, goal_version: int) -> bool`** — **lifts the fence and
>   removes no record**: where the record stands at a version **at or below** `goal_version` it
>   raises the record to `goal_version` with the fence **lifted**, and answers whether a standing
>   fence was lifted — **`True` where one was standing, `False` where it was already lifted**. **A
>   record standing at a higher version is left exactly as it was and `False` is answered**, which
>   is what keeps a stale caller from unfencing a later closure, and **a goal the store holds no
>   record of is answered `False`, has none written and raises nothing**. **It settles nothing,
>   revives nothing and reads no clock**; a row already `GOAL_CLOSED` is retired and no edge leaves
>   it (§2).
>
> **The record is one per goal — a `goal_version` and whether the fence stands — and neither
> member lowers it and neither removes it; only `clear` does** (below). **That is what makes it a
> watermark and not a latch**, and both members read it the same way: **a call carrying a version
> below the record's writes nothing and answers its empty answer** — `0`, or `False` — which is
> the store's whole defence against an act that read the goal before an intervening closure or
> reopen and arrived after it.

> **The version a caller passes is the one its own status write *expects*, never the one that write
> returns**, and that holds at every call site. `set_goal_status` **advances** `Goal.version` and
> answers the goal as written (ADR-0250 §9), so an act holds two versions and **the record is keyed to
> the earlier**: a closing act passes the version the read its attempt came from found and its own
> closing write names as `expected_version`, and §2's reopen passes the version *its* `ACTIVE` write
> named. **A later act reads the goal only after the earlier act's write has landed**, so its version
> is strictly higher and its call raises the record above the earlier act's — and **the earlier act's
> later call, of either member, changes nothing**: a delayed `clear_closure` unfences nothing, and a
> delayed `end_for_goal` ends no row of the request written since and leaves the fence exactly as it
> found it. **A lane passing the returned version at any call site has breached this clause**, and the
> failures it buys are the two the version exists to close: a reopen unfencing a closure that overtook
> it, and a closing act retiring the authority of a request established after it.

> **Normative — the record is a write fence and not a second kind of record, and it binds `record`
> alone.** **`GoalAuthorizationStore.record` refuses a row whose `goal` stands fenced**, decided **in
> the same indivisible step as the write**, and refuses it with **`InvalidAuthorizationError`** — the
> class ADR-0254 §16 gives *"a write this store does not admit"*, one further entry in that section's
> list and **no new class**. **`settle` gains no conjunct and needs none**: `end_for_goal` leaves the
> goal no `PROPOSED` row, so a settlement naming one finds it `GOAL_CLOSED` and answers
> **`NOT_AT_SOURCE`** truthfully on ADR-0254 §1's ratified graph. **`AuthorizationSettlement`
> therefore stays closed at four members** and no refusal of this decision is an exception where a
> result is owed. **What the record holds is one goal's closure watermark — a version, and whether
> this store admits a row of that goal — and it is neither an authority, nor coverage, nor a row**: it
> carries no basis, no instant, no expiry and no disposition, and `export` returns the rows exactly as
> ADR-0254 §16 fixes them.

> **Normative — `clear` erases the records with the rows, and §1's universal is stated absent a
> `clear`.** ADR-0254 §16 rules that **`clear` erases the store wholesale and returns the count**, and
> **the closure records go with the rows**: a record is keyed by a goal identifier, a goal identifier
> is Tier-1 user data (ADR-0254 §16, ADR-0004 §1), and one surviving a wholesale erasure would be a
> retained identifier of a user who asked for everything to be forgotten. **A record whose fence is
> lifted goes exactly as a standing one does, and `clear` is the only thing that erases either** — the
> watermark's cost, one record per goal this store was ever told closed, alongside the rows of that
> goal it already holds. **`clear` answers the count of rows unchanged**, a record being no row. **So
> the ending's universal — no row of a closed goal stands and none can be recorded — holds *absent a
> `clear`*, and after one a turn that read the goal open before the closure can record a row under
> it.** That is stated rather than closed, because **the alternative is worse in the direction that
> matters**: the only fix is retaining the goal identifiers of a cleared store, and what a `clear`
> leaves is a store with no rows, no history and no authority to inherit. **No lane retains a record
> across `clear`, reconstructs one afterwards, or reads `PlanStore` to rebuild one.** **The record is
> deleted with the rows and is carried by no export and no surface, and that is stated rather than
> left silent.** ADR-0254 §16 states the data rights over the store's **rows** — *"`export` returns
> a portable snapshot of every row"* — and names what is Tier 1 in one, *"a goal statement, an
> argument value and a span of the user's words"*. **A closure record carries none of it**: a goal
> identifier, a version and whether the fence stands, and no statement, value, span, basis, instant
> or disposition. **The identifier is the goal's**, which `PlanStore.export` carries as a matter of
> course (ADR-0250 §9) and which this store's rows of that goal carry where it holds any — **and
> where it holds none, that identifier is the whole of what is retained**, stated rather than
> rounded away. **What it is owed and takes is deletion**: `clear` erases it with the rows, on §16's
> own terms and with no `delete(id)` for either. **And it accumulates no faster than what §16 keeps
> for good**, one record per goal closed against one row per authorization retained forever under
> that same rule. **A lane that adds a closure record to `export`, mints a type for one or renders
> one on ADR-0254 §11's surfaces has breached this clause**; a surface for it, if ever wanted, is
> that section's decision.

> **Normative — two writes, not one, and the fence is taken first.** The ending and the `GoalStatus`
> write are **two writes in two stores** and the corpus offers no transaction across them — ADR-0255
> §6 states the constraint one store over, *"`PlanStore` offers no multi-write commit"* — so **no lane
> states, implements or tests them as one**. `orchestration` calls `end_for_goal` **after the read a
> closing-write attempt's `expected_version` comes from has found the goal open, and strictly before
> that attempt**, and on the `ABANDONED` path that closing write is `PlanStore.close_goal_abandoned`
> (ADR-0261 §2), whose three writes stay one indivisible step and gain nothing here. **The order is
> what makes the ending total rather than best-effort**: from the instant `end_for_goal` returns, and
> for as long as the fence it raised stands, no row of that goal stands `PROPOSED` or `ESTABLISHED`
> and none can be recorded, so the closing write cannot be raced by an establishment. **Taken after
> the status write it would be exactly that race**, and no lane reverses it.

> **Normative — what each failure leaves, and the closing act compensates nothing.** **Where
> `end_for_goal` raises, the closing act ends there having written nothing on that attempt**, and on a
> **first** attempt that is nothing at all — no status, no attempt commit, no fence — and a retry
> re-runs the act whole. **On a retry attempt it leaves what the first attempt and any intervening act
> left** — a fence standing where nothing has lifted it, repaired as below. **Where it succeeds and
> the closing write does not, the act propagates and clears nothing**: the rows stand `GOAL_CLOSED`,
> truthfully under §2's meaning — they were ended by a closing act of their goal, which is what
> happened — the goal is left open and fenced, and **every call of it asks** until the user repairs
> it, which is ADR-0254 §12's own stated cost for its rung 3, *"every call of that goal asks"*,
> reached by one further route. **The repair is the user's own two acts and no mechanism**: abandoning
> the goal fences what is fenced, ends nothing already ended and closes it truthfully; reopening it
> then ends any survivor and clears the fence (§2). **No lane adds a sweep, a repair pass, a start-up
> scan, a timer or a durable act identity for either failure.**

> **Normative — why the act does not compensate, stated because the obvious design is the one
> refused.** A `clear_closure` on a failed closing write **cannot tell its own orphaned fence from one
> a concurrent act is relying on**, and the version does not separate them: two acts whose first reads
> both found the goal open at version *v* fence at *v* alike, so a compensation carrying *v* clears
> the record the act that actually closed the goal stands on, leaving a closed goal unfenced and a
> stale turn able to record under it. **That is the state this decision exists to close, and the
> compensation would reach it on the ordinary closing path** — not in a booked residual (§8, §9) but
> every time a closing write failed — so the compensation goes, not the fence. **The cost is
> asymmetric in the safe direction**: compensating risks an authority under a closed goal, not
> compensating costs questions under an open one. **No lane restores it under any name**, a repair
> call, a best-effort clear or a retry included.

> **Normative — the ending is taken once per closing-write attempt, ADR-0261 §2's retry included.**
> That section retries a `StaleExecutionError` from `close_goal_abandoned` **once**, re-reading and
> re-taking the act's own first-read decision, and **only where the re-read finds the goal still open
> does it call the closing write again, under the version it has just read** — so **that attempt takes
> its own `end_for_goal` first, carrying that same version**. **Without it the retry closes a goal
> whose rows have moved under it**: between the two attempts another act can close the goal and a
> reopen can lift the fence and admit a fresh row, which a retried closure taking no ending would
> leave `ESTABLISHED` under the goal it has just closed — §1's universal broken on a path the act
> itself reaches. Where nothing touched the rows it answers `0` and costs nothing. **An attempt that
> is never made takes no ending** — an act answering `NO_SUCH_GOAL` or `ALREADY_CLOSED` from its
> **first** read calls `end_for_goal` not at all, and one answering either from its **re-read** called
> it once, for the attempt it did make, leaving that fence **standing**: the state the act that closed
> the goal left. **A stale loss is not a failed closing write and takes neither branch of the clause
> above**: the act retries as ADR-0261 §2 directs, and whichever way the re-read goes no fence is
> lifted. **No act calls `clear_closure` at all** — that member has exactly one caller, §2's reopen.

> **Normative — a `PROPOSED` row is ended with the rest, and ADR-0254 §1's no-sweep clause is
> untouched.** That clause reads *"**No sweep, no timer, no reclaim and no start-up scan** settles
> it"*, and the closing act is none of the four: it is a **user act's own write**, taken once, on the
> goal the user closed. **ADR-0250 §12 already settles the goal's open `GoalQuestion` `WITHDRAWN` in
> that same act**, so a closing act reaching a durable question of the goal is the corpus's own shape
> and not a mechanism minted here. **Ending it is what makes the ending total**: a proposal left
> standing could be answered after a later reopen and would then cover calls of the reopened request
> under a bound the user stated for the request that ended, which is the failure this decision exists
> to prevent reached one disposition over.

### 2. `GOAL_CLOSED`: a seventh member, retired, and the ended row never revives

> **Normative.** **`AuthorizationDisposition` gains one member and closes at seven**:
> **`GOAL_CLOSED`**, valued by lower-cased member name like the other six, meaning **this row was
> ended by a closing act of its goal**. **The meaning is stated over the act and not over the goal's
> resulting status, and that is deliberate**: the ending and the `GoalStatus` write are two writes in
> two stores (§1), the ending is taken first, and a closing write that then fails leaves rows this
> member describes truthfully — they *were* ended by an act that was closing their goal — where a
> member meaning *its goal closed* would assert an event that did not occur. **What the member never
> means is that the row lapsed, that the user withdrew it or that a later row replaced it**, which is
> what distinguishes it from the three §2 refuses below. The vocabulary is *added to and never
> renamed*, which is ADR-0254 §1's own rule and the licence for this member. **`GOAL_CLOSED` is
> *retired*: no edge leaves it**, so it joins `DECLINED`, `EXPIRED`, `REVOKED` and `SUPERSEDED` as the
> **fifth** member `settle` refuses a move out of, and **it is never live**, §1's liveness predicate
> being stated over `ESTABLISHED` alone.

> **Normative — the graph gains two edges and `settle` admits both, the graph staying stated once.**
> ADR-0254 §1's transition graph gains **`PROPOSED → GOAL_CLOSED`** and **`ESTABLISHED →
> GOAL_CLOSED`** and closes at **seven** edges. `PROPOSED` and `ESTABLISHED` stay **the two members an
> edge leaves** and no other edge exists. **`settle` admits both like any other edge** and answers
> `AuthorizationSettlement` unchanged — `SETTLED`, or `NOT_AT_SOURCE` for a row standing anywhere
> else; **`WOULD_DUPLICATE` is unreachable on either**, that member being reachable only on a
> settlement to `ESTABLISHED`. **A store that refused the member would be a second place the
> vocabulary is decided** (ADR-0250 §9's own sentence, one store over), and the refusal has nowhere
> truthful to go: `NOT_AT_SOURCE` would be false of a row standing exactly at the edge's source, and
> an exception is a refusal where a result is owed, which §1 declines for this decision — so a
> carve-out would need a **fifth `AuthorizationSettlement` member**. **§6's writer clause carries the
> discipline instead, and carries it as an obligation on the lane rather than as a refusal by the
> store**: the store admits the edge, a single-row settlement to `GOAL_CLOSED` is a **breach of §6**
> and not a state the contract prevents, and that is the shape ADR-0254 §15 already gives every write
> of this store — *"written and settled by `orchestration` and by nothing else"*.

> **Normative — why a seventh member and not one of the six, stated because ADR-0254 §1 already
> answers the same question once.** **`EXPIRED` is refused** for that section's own reason, read one
> ending over: it *"is the answer a question never got, and re-using it for a lapsed authority would
> make the two indistinguishable in a listing"* — and a row that ended with its goal is a third thing
> again. **`REVOKED` is refused** because it records the **user's** withdrawal, and a surface that
> showed a system act as one would attribute to the user an act they did not take. **`SUPERSEDED` is
> refused** because it names a later row that replaced this one, and there is none. **A `bool`, a flag
> or a second field on the row is refused** because ADR-0254 §1's field list is closed and *"a lane
> adding a member is changing this decision rather than implementing it"*, which ADR-0256 §4 has
> already declined to reopen once.

> **Normative — one member for both edges, and the ambiguity ADR-0254 §1 warns of does not arise.** A
> row reached from `PROPOSED` and one reached from `ESTABLISHED` record **one fact** — this row was
> ended by a closing act of its goal — and the two are not confused on any surface, because **neither
> is rendered on one**: `standing` returns `ESTABLISHED` rows alone (ADR-0254 §16), so it never
> offered a `PROPOSED` row and no longer offers an ended one. **Where they are told apart is `recent`
> and `export`**, which carry the row whole — its `confirmation`, its `coverage`, its `origin` and its
> basis — and that is where an auditor reads. **No lane mints a second member, a field or a flag to
> distinguish them.**

> **Normative — a reopen ends, then clears, and both are taken after the `ACTIVE` write and only on a
> successful one.** **`orchestration` calls `end_for_goal` and then `clear_closure` immediately after
> ADR-0250 §13's `GoalStatus.ACTIVE` write succeeds**, both carrying that write's own
> `expected_version` (§1), and neither before it and neither on a write that was refused. **The ending
> is taken first and it is what makes the reopen total rather than dependent on the closure having
> run**: on a goal this store was told about it answers `0`, and on one it was not — a database
> predating this decision (§9) — it ends the rows the closure never reached, the only route by which a
> row written before a closure otherwise reaches a call of the reopened goal. **It settles them
> `GOAL_CLOSED` truthfully**: their goal *was* closed, by an act this store was never told of, and the
> reopen's ending completes that act rather than asserting a closure of its own — which is why §2's
> member is stated over the closing act and not over the status the goal now holds. **The clear is
> taken second and lifts the fence the ending just wrote**, the record staying at that version with
> the fence down. **The compare-and-swap is what serialises two reopens**: `set_goal_status` advances
> `Goal.version` and refuses a stale `expected_version` (ADR-0250 §9), so of two acts reopening one
> goal exactly one writes `ACTIVE`, exactly one takes the pair, and the loser re-reads and finds a
> goal that is open — which ADR-0250 §13 does not reopen. **Between the `ACTIVE` write and the clear
> the goal is fenced**, so a turn reading it open in that instant is refused a row and **asks**, which
> is the fail-closed direction. **No lane clears a fence anywhere else or on any other act**,
> `clear_closure` having exactly this one caller (§1).

> **Normative — a failure of either reopen call leaves whatever the closure left, and the two cases
> differ.** **Where either raises after a successful `ACTIVE` write the act propagates**, and no later
> turn reaches this call site, a turn finding the goal open being a continuation and not a reopen
> (ADR-0250 §13). **Where a closure under this decision had run a fence stands**: the goal is left
> `ACTIVE` and fenced, **every call of it asks**, and that is §1's failed-closing-write state from the
> other side at the same cost. **Where it had not — §9's pre-decision database, whose closure wrote no
> fence — an `end_for_goal` that raises writes none either**, its step being all-or-nothing, so the
> goal is left `ACTIVE`, **unfenced**, its legacy row still `ESTABLISHED` and still covering a call
> **until its own `expires_at`**. **That is §9's prospectivity bound exactly, no worse than the
> pre-decision behaviour and the state the reopen exists to improve on rather than one this decision
> creates**; **no clause claims every call of such a goal asks.** **The repair is the user's own two
> acts in both cases**: abandoning closes the goal truthfully and, on the legacy path, fences it and
> ends the row for the first time; reopening then ends any survivor and clears the fence. **So no goal
> is permanently unable to authorize and no legacy row outlives its own expiry**, and **no lane adds a
> sweep, a start-up scan, a retry loop, a repair pass or a two-phase reopen for either.**

> **Normative — a reopened goal is a new attempt and a new act, and no ended row revives.** ADR-0250
> §13's reopen writes `GoalStatus.ACTIVE` and opens a new attempt at `UNDERSTAND`. **No row settled
> `GOAL_CLOSED` is restored, re-opened, re-established or read as an authority by it**: the member is
> retired, no edge leaves it, and ADR-0254 §1's posture for the same question binds — *"`SUPERSEDED`
> is retired and no edge leaves it, so nothing un-supersedes one"*. **And no row of the closed request
> survives in any other disposition either**, §1 having ended the goal's `PROPOSED` rows with its
> established ones, so **no row written before the closure can ever cover a call of the reopened
> goal.** **That claim is stated over the instant of the *write* and is not a claim about the act the
> write is grounded in**: a turn that read the goal open before the closure and is still holding its
> `record` when the reopen clears the fence writes **after** the closure and is admitted, carrying an
> authority the user gave for the request that ended (§8, the residual it books). The reopened goal's
> authority is otherwise established afresh, by a path-(i) proposal the user answers or by a
> path-(iii) opening act, exactly as a first attempt's is, and ADR-0254 §1's uniqueness is satisfied
> by construction.

> **Normative — the ending ends the authority and never the interpretation.** ADR-0250 §13's
> *"Reopening preserves everything the goal holds"* and ADR-0249 §1's append-only chain bind entire,
> so a `USER_STATED` constraint of the goal — the money ceiling among them (ADR-0266 §1) — **survives
> its goal's closure and its reopening unchanged**. What a later request re-establishes is the
> **row**, minted from *"the user's own recorded words of this goal"* (ADR-0254 §1), any turn of the
> goal and not only the latest. **No clause of this decision edits, retracts, elides or re-grounds an
> interpretation revision, and no lane reads a closure as licence to ask the user to restate a
> bound.**

> **Normative — what leaves the listing, stated rather than discovered.** `standing(goal)` returns the
> `ESTABLISHED` rows and nothing else (ADR-0254 §16), so **a row ended `GOAL_CLOSED` appears in
> `standing_authorizations` not at all**, exactly as a revoked or superseded one does not. **It is not
> revocable**, there being nothing left to withdraw and no edge out. **It is deleted by nothing**:
> ADR-0254 §12's no-deletion rule binds entire, `recent` and `export` carry it whatever its
> disposition, and a user reading the record of a finished request still finds what they authorised,
> what it covered and when it ended. **No lane adds a surface, a carrier, a member or a second
> rendering for it**, and the listing renders exactly what ADR-0254 §11 fixes.

### 3. The retention window is the backstop, and no instant is moved

> **Normative.** **ADR-0256 §1's rung is the expiry of a row no closing act of its goal ends, and of
> no other**, which is a wider set than *a row whose goal never closes* and deliberately so. Every
> clause of that decision binds unchanged: the rung is taken on ADR-0254 §12's paths (i) and (iii) at
> the instant the row is written, from `Settings.episode_retention` and `proposed_at`; `Settings`
> gains nothing; a correction takes no rung of the ladder; §3's `None` case still writes no row at
> all; and §5's narrowing correction is untouched. **What is subordinated is only the claim that the
> window is the horizon**: a row standing when a closing act of its goal runs is ended by that act, so
> its own `expires_at` is an **upper** bound and not the horizon. **The bound is stated over the act
> and not over the two instants**, which is §2's meaning read one section on: a row the closing act
> never reached — written after it, or under a closure that predates this decision (§9) — is **not**
> ended by it and lapses on its own `expires_at` exactly as ADR-0256 ratifies, which is §8's booked
> residual and §9's prospectivity bound respectively. **A lane reading this as "the earlier of two
> instants" has read a rule this decision does not state**, and would owe a sweep no clause here
> licenses.

> **Normative — no instant is moved, shortened, recomputed or re-read, and the row ends by a
> disposition alone.** ADR-0254 §12's *"the expiry is taken once, when the row is written, and is
> never recomputed"* binds **entire**. **This decision moves no `expires_at`**, on any path, for any
> reason: `end_for_goal` writes the disposition and its instant and nothing else, so a row ended
> `GOAL_CLOSED` still carries, and `export` still renders, the horizon the act was granted under. **A
> lane that shortened an expiry to express this ending has breached this clause**, and would have made
> the instant the user was shown at the act untrue.

> **Normative — the window keeps the one job it had, and it is the one ADR-0256 §1 argued for.** A
> goal that never closes — the user stops engaging it, no act abandons it, A10 never verifies it — has
> no closing write for §1 to hang an ending on, and its rows lapse on the window exactly as ratified.
> **So do the rows a closing act ran but never reached**: a row written after the closure and admitted
> at a reopen (§8), and a row under a closure predating this decision (§9). **Those three cases are
> the whole of the backstop**, and ADR-0256 §1's ground for the figure is undisturbed: *"an authority
> takes the window the deployment keeps the record of its act for, and never a window minted for it"*.
> **No lane reads this decision as a reason to lengthen, cap, default or re-derive that window**, and
> ADR-0256 §6's exclusions — `RecipientGrant.expires_at` and ADR-0247's configured-provider authority
> — bind entire and are reached by no clause here.

### 4. The uncertain outcome is not an exception, because nothing closes the goal under one

> **Normative.** **This decision adds no exception for an uncertain outcome, and needs none, because
> it writes no `GoalStatus` and adds no producer of one.** While a step of the goal stands
> `INDETERMINATE` the attempt stands `EFFECT_UNRESOLVED`, which ADR-0255 §6 makes *"neither a terminal
> member nor one of the three ADR-0249 §5 derives paused from"*; ADR-0249 §4 rules that *"An attempt
> reaching a terminal state **does not** move the goal's status"*; and `ACHIEVED` has one producer,
> **A10's verification against the goal's criteria**, which an unresolved effect has not supplied.
> **So the goal is not closed, no ending fires, and the established row stands** — which is the
> owner's uncertain-outcome case satisfied by the ratified route rather than by a clause of this
> decision.

> **Normative — reconciliation resolves the step and closes nothing.** ADR-0259 §4's pass *"writes
> **no `GoalStatus`**"* and its act 4 returns the attempt to `RUNNING` where no step of it stands
> `INDETERMINATE` or `RUNNING`. **Whether the goal then closes is A10's, by the ratified route and by
> no shortcut this decision offers**: a resolution is a repair of a record and is not a verification.
> **No lane reads a resolved effect, a released attempt or a reconciliation pass as a closing act**,
> and the pass calls `end_for_goal` in no case.

> **Normative — the user's cancellation closes such a goal and ends its authority with it, and that is
> the ruling working rather than an exception to it.** ADR-0261 §2's act closes a goal holding an
> outstanding effect and reports it, answering `ABANDONED_EFFECT_IN_FLIGHT` (§6). **The ending fires
> there like any other `ABANDONED` write** — the user ended the request, and an authority for a
> request the user ended is what this decision exists to retire. **What was already dispatched is
> unaffected**: ADR-0261 §5 binds entire, the effect row is released by nothing, and *"no lane reads a
> reopened goal or a fresh plan as licence to repeat an act"*.

### 5. The offer carries the price, and the acceptance is the authorisation act

> **Normative — an offered change is a path-(i) proposal and the acceptance is its answer.** Where the
> assistant offers a change — *"move it to Sunday — that is 135 euros"* — the offer is put as the
> `CONFIRM` ADR-0254 §1's **path (i)** proposes a row against, and the user's acceptance settles that
> row on §1's **`PROPOSED → ESTABLISHED`** edge. **That is the whole mechanism and this decision mints
> none of it**: no surface, no carrier, no member, no edge and no second question. **"A new request
> each time" is not "a separate money prompt each time"**, because the request and the money are one
> question and the acceptance is one answer.

> **Normative — the amount is rendered by the machinery that already renders it, and a lane adds
> nothing to make that true.** `Confirmation.authorization` carries an `AuthorizationProjection`
> (ADR-0254 §11) whose `coverage` and `expires_at` that section requires and whose `quote` ADR-0267 §7
> transcribes from the proposed row's `quoted` — the governing quote for the request's intended
> action, read from the goal the row was built from. **So the figure the acceptance is taken over is
> on the screen the user answers**, which is ADR-0254 §11's own test — *"A confirmation that
> establishes a bound without naming it is not a confirmation of that bound"* — met by a value the
> ratified projection already carries. **No lane re-selects a quote to render one** (ADR-0267 §7), and
> **no lane reads this clause as widening what a confirmation names.**

**The ruling's two "make it Sunday" cases are one rule read at two instants, and ADR-0266 §7 is
reached and superseded in nothing.** That section's worked case — *"'Make it Sunday' replans and the
re-quote is `135`: that quote governs, `135 ≤ 150`, and **still no question**"* — runs at phase 3 of
a **live** goal, before the booking executes; the row stands `ESTABLISHED`, route (d) covers the
re-quoted call, and every word of it is true after this decision. The owner's *"'Make it Sunday'
after a completed booking is likewise a new request modifying a completed result"* is the **other**
instant: the goal closed, §1 ended the row, and the change is offered and accepted under §5. The two
never meet, because a goal is closed or it is not, and what tells them apart is the goal's status
and not the words the user used.

### 6. Writer clauses, and what this decision leaves exactly as it stands

> **Normative — one writer, and the call sites are named exhaustively.** **`orchestration` calls
> `end_for_goal` and `clear_closure`, and nothing else does.** `end_for_goal` is called at exactly
> three places and no fourth: before each closing-write attempt of ADR-0250 §12's `ABANDONED` act
> (§1), before A10's `ACHIEVED` write (§1, §9), and after a **successful** `ACTIVE` write on ADR-0250
> §13's reopen (§2). `clear_closure` is called at exactly **one** and no second: after that same
> reopen's `end_for_goal`, in that order (§2). **No act compensates a failed closing write**, which §1
> states and grounds. **No other act, pass, sweep, scheduler or start-up scan calls either**, and
> ADR-0259 §4's reconciliation pass calls neither (§4). That is ADR-0254 §15's clause reaching two
> members — an `Authorization` is *"written and settled by `orchestration` and by nothing else"*. **No
> store, no `ActionPolicy`, no `AuditTrail`, no interface adapter, no reader, no tool and no model
> output calls either, and no model output decides that a goal has closed.** `GoalAuthorizations` and
> `AuthorizationResolution` gain **nothing**: the policy's face still carries `live_for` alone and the
> trail's `resolve` alone, so neither can reach either member (ADR-0254 §16's three faces, unchanged).

> **Normative — `GOAL_CLOSED` is written through `end_for_goal` alone, and this is a writer clause and
> not a store refusal.** **No act settles a single row to it through `settle`**, though §2 leaves both
> moves admissible **and the store refuses neither**: a row ended on its own would assert that a goal
> closed when none did, and the fact this member records is a fact about the **goal**. **What the
> store guarantees is `end_for_goal`'s own step** — no partition of the rows it saw (§1) — and what
> keeps a single-row settlement from happening is this clause standing on ADR-0254 §15, which is where
> every write of this store is disciplined. **A lane that wrote `GOAL_CLOSED` from anywhere but the
> closing act has breached this clause.**

> **Normative — §13's recheck and §7's trail invariant bind entire, and this decision adds no residual
> to either.** ADR-0254 §7's route-(d) refusal reads the resolved row's `disposition` and requires
> **`ESTABLISHED`** — *"the existence, the kind, the unrevoked, the unsuperseded and the answered
> check at once, since every other disposition is retired and none of them is live"* — and that reason
> is true of `GOAL_CLOSED` as it is of the other four, so the check is unchanged and needs no
> conjunct. **A goal closing between `live_for` and `AuditTrail.record` refuses the write**, exactly
> as ADR-0254 §20's arm 4 records for a revocation landing in the same window. **A goal closing
> between the ruling and a claim already taken is ADR-0254 §13's stated residual and §19's A9 booking,
> unnarrowed and unwidened**: a settlement is a settlement, and this decision claims nothing stronger
> about its own than that section claims about a revocation.

> **Normative — what is untouched, named so a lane cannot read silence as licence.** `Authorization`'s
> **field list stays closed** and gains nothing. `CoverageMember`, `ValueBound`, `BoundedArgument`,
> `ActionQuote` and every reading over them are untouched, and **condition 6 is not reached in any
> limb** (ADR-0266 §7, ADR-0267). `AuthorizationSettlement` stays closed at four,
> `AuthorizationOrigin` at two, `AuthorizationProjection`, `AuthorizationView` and `CoverageView` gain
> no member, and `core/errors.py` gains no class. `core.config.Settings` gains **nothing at all**.
> `GoalStatus`, `AttemptState`, `AttemptOutcome`, `GoalAbandonment` and `AttemptPhase` gain **no
> member**, and no writer of any of them is added, removed or re-attributed.

### 7. What this records against earlier ADRs, clause by clause, under ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a reader holding only
that ADR now act differently, or read one of its clauses more widely than it now holds? For each
limb below the answer is yes, and the sentence that becomes false or over-wide is named. **Six
places, in three documents.**

1. **ADR-0254 §1's `AuthorizationDisposition` clause**, in its closure and its retired enumeration:
   *"closed at exactly **six** members"* becomes seven, gaining `GOAL_CLOSED`, and *"`DECLINED`,
   `EXPIRED`, `REVOKED` and `SUPERSEDED` are *retired*: no edge leaves them"* enumerates four where
   there are now five. A reader holding only §1 authors an enumeration that cannot spell the ending
   an authority now has, and a `settle` that refuses a move out of four dispositions where a fifth
   is retired. **The rule that licenses the addition is that section's own** — *"The vocabulary is
   added to and never renamed"* — so nothing is renamed and no member's meaning moves.
2. **ADR-0254 §1's transition graph, in its edge count**, and **§1's `PROPOSED`-row clause, in the
   settlers it enumerates**. The graph's *"stated whole, and there are exactly **five** edges"*
   becomes **seven**, the two new ones being `PROPOSED → GOAL_CLOSED` and `ESTABLISHED →
   GOAL_CLOSED`. **Its two other assertions stand verbatim and are relied on**: *"`PROPOSED` and
   `ESTABLISHED` are the two members an edge leaves"*, which both new edges satisfy, and *"no other
   edge exists"*, read over the seven. **`settle`'s own clause stands verbatim but for the count** —
   it still *"moves a row along one of §1's edges under compare-and-swap and refuses every move that
   is not an edge"* — and `AuthorizationSettlement` is unmoved at four members. And §1's clause that
   an expired proposal is settled *"by the **first operation that reads it**, and there are exactly
   **two** — a `live_for` read, and the answer that names it"* now has a **third** settler in
   `end_for_goal`, which settles it `GOAL_CLOSED` rather than `EXPIRED`. **That clause's negative
   limb is untouched and is what makes the addition admissible**: *"**No sweep, no timer, no reclaim
   and no start-up scan** settles it"* stays true word for word, the closing act being none of the
   four but a user act's own write — the act that ADR-0250 §12 already has settling the goal's open
   question `WITHDRAWN`. Its *"a `PROPOSED` row neither operation reads again stays `PROPOSED`"* is
   narrowed to a goal that does not close. A reader holding only §1 ships a graph an ending cannot
   be expressed in, and leaves a pre-closure proposal answerable after a reopen.
3. **ADR-0254 §16's store roster, in the signature count**, and **§16's `InvalidAuthorizationError`
   clause, in its enumeration of refused writes**. The **eight** signatures that section states *"in
   full, because a roster of names is not a contract"* become **ten**, gaining `end_for_goal(goal,
   /, *, at, goal_version) -> int` and `clear_closure(goal, /, *, goal_version) -> bool`. And the
   list of writes `record` refuses — *"a second `ESTABLISHED` row of one goal and declaration id, a
   path-(ii) row that fails the transcription or non-widening check …"* — gains **one further
   entry**, a row whose `goal` the store holds fenced. **That class is reused and no class is
   minted**, §16's *"A refusal is the caller's error and a fault is the store's"* split binding
   entire, and **`AuthorizationError` and `core/errors.py` are untouched**. `GoalAuthorizations` and
   `AuthorizationResolution` gain nothing, so **§16's three-faces construction stands entire**, as
   do its detached-snapshot rule, its clock disciplines — neither new member evaluates liveness and
   neither reads a clock — its `standing` clause, its `settle`-outcomes clause, its data-rights
   clause, its `export` and `clear` clauses and its `PROTOCOL_VERSION` clause. **§16's
   `core/types.py` and `core/errors.py` rosters take no scope**: this decision adds no type, no
   field and no class, so the counts ADR-0266 §9 and ADR-0267 §9 left them at are unmoved. A reader
   holding only §16 implements a store whose contract has no ending on it and which admits a row for
   a goal that has closed.
4. **ADR-0254 §20, in two limbs.** **Lane 1's *"The **eight** store signatures"*** goes with §16's
   roster above and becomes ten. **And arms 37 and 55**, each in its edge count and its
   retired-disposition enumeration — arm 37's *"Each of the five edges succeeds under
   compare-and-swap; every other move is refused, with one test per retired disposition"* and arm
   55's *"Each of the five edges from its own source → `SETTLED`; … one test per retired
   disposition"* — which now run over seven edges and five retired dispositions; **and arm 37 in one
   further limb**, its *"a row read after its `expires_at` while still `PROPOSED` is settled
   `EXPIRED` by a `live_for` read and by the answer that names it, **and by no other operation**"*,
   whose last limb is false of `end_for_goal`. **Every other assertion of both stands verbatim**,
   their subject being `settle`, which still refuses every move that is not an edge and still cannot
   leave a retired member; what grows is the number of cases each arm is stated over. **Every other
   arm of §20 is untouched**, arm 4's revocation-between-`live_for`-and-`record` case conspicuously
   so, which §6 above reads as the shape of this ending's own race rather than as a case that moves.
5. **ADR-0256 §1's bound clause, in the direction of the bound alone**, and with it that decision's
   title: *"**A row written on this rung is bounded by the turn-retention window in force at its own
   write, measured from `proposed_at`, and by nothing longer**"* stays true as an **upper** bound
   and stops being the horizon — such a row is ended by a closing act of its goal where one reaches
   it, and lapses on that instant where none does. A reader holding only ADR-0256 reads the window
   as when the authority ends and would report a live authority over a finished request for the rest
   of it. **Every other clause of ADR-0256 binds entire and several are what this rests on**: §1's
   rung and its `proposed_at`-only read, its no-new-reader rule and its illustrative list of rows
   that outlive an act's record; §2's `Settings`-gains-nothing, read-once and fail-closed
   arithmetic; §3's `None` case, which writes no row at all and is untouched; §4's rendering and its
   refusal of a `source` member; §5's narrowing correction; and **§6 entire**, whose *"No row is
   moved, shortened or settled by anything that happens to the act's own record"* is stated over the
   **act's record** and is reached by no clause of this decision — what ends a row here is a
   **closing act of its goal**, which is neither an episode nor a conversation. §§7-11 stand as they
   are.

6. **ADR-0250 §13's enumeration of what a reopen does, in that enumeration alone**: *"Reopening
   writes `GoalStatus.ACTIVE` through `PlanStore.set_goal_status` (§9), opens a new attempt (§12)
   and engages the goal (§1)"* gains a fourth and a fifth act taken in order **immediately after a
   successful `ACTIVE` write** — `end_for_goal` over that goal and then `clear_closure` over it
   (§2), both carrying that write's own `expected_version`. **Without the fifth** the goal stays
   fenced and the reopened request can establish no authority at all, every call of it asking for
   ever; **without the fourth** a database written before this decision (§9) reopens with its old
   rows still standing `ESTABLISHED` and they cover the new request. **The ordering is the
   enumeration's own**, the `ACTIVE` write's compare-and-swap being what makes exactly one of two
   racing reopens the one that takes the pair. A reader holding only §13 ships a reopen that cannot
   authorise anything. **That enumeration alone, and nothing else in §13**: its *"Reopening
   preserves everything the goal holds"* clause binds **entire** and is what §2 rests on — the
   interpretation chain, the `interpretation_elided` count, the `conversation_id`, the earlier
   attempts and the no-replay rule are each untouched, an authorization being none of them — and so
   do §13's `EngagementDisposition.REOPENED` case, its explicit-reference rule, its no-identifier
   rule, its `conversation_id`-provenance clause, its candidate clause and its resolves-against-the-
   `PlanStore` clause. **§§1-12 and §§14-21 stand entire**, and two of them are read rather than
   changed: §1's open/closed division, which §1 of this decision takes as its trigger, and §12's
   abandonment sequence, which gains nothing here.

**Reached and superseded in nothing, recorded because a reader would otherwise look for a scope.**
**ADR-0266 §7's worked case** is stated at phase 3 of a live goal and every word of it survives (§5
above). **ADR-0267 §7** is relied on and unmoved, `quoted` being provenance no comparison reads.
**ADR-0261 §2 and §5** bind entire: this decision adds no conjunct to `close_goal_abandoned`,
`set_goal_status` or `open_attempt`, moves no attempt and no step, and leaves §2's single
re-read-and-retry as it is — §1 states a store call `orchestration` takes around each attempt that
section already makes, changing neither the attempt, nor what the re-read decides, nor how many
there may be. **ADR-0250 §1's division is read and not changed**, and §12's abandonment sequence
gains nothing. **ADR-0249 §4** is quoted rather than narrowed: `ACHIEVED` and `BLOCKED` gain no
producer here.

### 8. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it toward any of
> them.

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
- **Clearing a fence left standing by a closing write that failed, otherwise than by the user.**
  §1 refuses the compensation with its reasons and states what the failure leaves: a goal open,
  its rows ended, and every call of it asking, repairable by the user abandoning and reopening it
  and by nothing else. **No operator surface, sweep or start-up scan for that state is minted
  here.** Fired by a measured occurrence, or by the decision that lands an operator surface on
  this store — which is ADR-0254 §19's *"Retention for this store beyond `clear`"* entry's own
  neighbourhood.
- **The cross-store linearisation of a settlement against an act in another store.** §1's fence
  closes the establish-against-closure race **inside one store**; it says nothing about a call
  already claimed when its goal closes, which is ADR-0254 §13's stated residual window and
  §19's booking to **A9**, declined there *"on ADR-0193 §9's own refusal of a cross-store
  linearisation"*. **This decision neither narrows nor widens it**, and no lane reads the fence
  as having closed it.
- **A `record` begun before a closure and admitted after a reopen has cleared the fence.** The
  fence refuses such a write **while it stands**, so the residual is a turn paused across **both**
  a closure and a reopen: its row is written after the closure, is admitted, and carries an
  authority given for the ended request. **This decision narrows the race and does not create
  it** — before it every delayed write under a closed goal stood, there being no fence at all —
  and closing it would take **a generation on `record` itself** and a rule for a turn that read
  *v* and writes at *v+2*. **§1's watermark is the retained floor and is not enough on its own**,
  `record` carrying no version to test against it: the ordering ADR-0193
  §9 refuses to have inferred from silence, *"a later ADR that wants a stronger ordering decides
  it explicitly and with an implementation in hand"*. **Booked to A9 with the entry above**, and
  **no lane adds a field, an argument or a retained generation to `record` on its strength.**
- **A viewing or export surface for the closure record.** §1 states why this decision adds none —
  ADR-0254 §16's export is over rows, the record carries no content, the identifier is the goal's —
  and **a reader holding ADR-0004 §6 to reach every retained datum reads it the other way**. This
  decision states the record, its deletion under `clear` and its bound, and books the surface rather
  than settling that reading. Fired by that reading being taken, or by an operator surface landing
  on this store (ADR-0254 §19).
- **`GoalStatus.ACHIEVED`'s producer (A10) and `BLOCKED`'s (A3).** ADR-0249 §4 reserves both and
  ADR-0254 §19 books both; this decision writes neither and states only what a closing write
  additionally owes.
- **Retention for this store beyond `clear`.** ADR-0254 §19's entry, untouched: a `GOAL_CLOSED`
  row is deleted by nothing, exactly as every other row is.

### 9. The lane cut, the wire, the stored shape, and the arms this decision owes

> **Normative — one lane, and the ground is that the two members have one caller between them.**
> **`core/types.py`'s `GOAL_CLOSED`, `core/protocols.py`'s `end_for_goal` and `clear_closure` and
> `record`'s further refusal, the `GoalAuthorizationStore` conformance suite's arms for each, the
> canonical fake in `ai_assistant.testing`, `SqliteGoalAuthorizationStore`'s implementation in
> `permissions/`, and `orchestration`'s three call sites — `end_for_goal` before each `ABANDONED`
> closing-write attempt, and `end_for_goal` then `clear_closure` after ADR-0250 §13's `ACTIVE` write —
> are one change.** ADR-0137 §2's construction is what makes it one — the contract rides with the
> primary production consumer whose demands shape it — and the demand here is total: a lane landing
> `end_for_goal` without its caller leaves a tree in which an authority never ends, and one landing it
> without `clear_closure` leaves every reopened goal unable to authorise anything. **It is a BREAKING
> contract change under golden rule 5 and is flagged as one**, and this ADR merges, ratified, before
> it (ADR-0015).

> **Normative — the `ACHIEVED` call site is A10's and is not this lane's.** `ACHIEVED` has no producer
> in the tree (ADR-0249 §4), so **the lane above wires `end_for_goal` on the `ABANDONED` close
> alone**, that being the one closing write that exists. **A10's lane calls it before its own
> `set_goal_status(…, ACHIEVED)` write, on §1's order and passing that write's own
> `expected_version`**, and **no lane ships a producer of a closed `GoalStatus` without it**.

> **Normative — `PROTOCOL_VERSION` does not move, and the ground is read off the tree rather than
> assumed.** ADR-0124 §9's test is *"a change to a wire-carried `core` type that makes a value one
> peer emits invalid for the other"*, and **no wire-carried value changes**: ADR-0254 §16 rules that
> *"**No `Authorization` crosses whole and no member of `GoalAuthorizations`,
> `AuthorizationResolution` or `GoalAuthorizationStore` is promoted**"*, the four carriages that do
> cross are projections, `AuthorizationView` carries `live`, a `bool`, and **not** a disposition, and
> `AuthorizationSettlement` — which does cross, through `revoke_authorization` — gains no member.
> **Neither `end_for_goal` nor `clear_closure` is promoted by anything.** **A lane that finds the tree
> disagrees takes the bump and records the correction in `wire/envelope.py`'s log**, rather than
> reading this clause as permission to skip one.

> **Normative — the authorization store's `schema_version` moves by exactly one and no migration is
> owed.** A file written after this decision may carry a `disposition` an earlier reader refuses, and
> carries a closure record earlier code does not know, which is ADR-0039 §10's mechanism as ADR-0261
> §10 applies it one store over. **No row is rewritten, re-dispositioned or back-filled and no goal is
> recorded closed by the upgrade** — so the migration is the version marker and the new storage, and
> nothing else. The tree holds **1** as a dated observation at `61f40e9f`. **No compatibility shim,
> lenient decode or tolerated-unknown entry is added.**

> **Normative — the ending is prospective, and the bound on what the upgrade leaves behind is stated
> rather than implied.** **This decision governs closing acts taken after it ships and retrofits
> nothing**, which is ADR-0247 §8(b)'s prospectivity — the shape ADR-0254 §12 already reads onto this
> very store, *"a later edit to the goal's `deadline` moves no row already written"*. **What that
> leaves is stated exactly**: a database written before this decision may hold an `ESTABLISHED` row
> whose goal was **already closed**, the closing act having run before `end_for_goal` existed, and
> **no upgrade ends it and no sweep finds it** — it stands in `standing_authorizations` and can cover
> a call of that goal **until its own `expires_at`**, which ADR-0256 §1 bounds by the turn-retention
> window in force at its write. **That is the pre-decision behaviour and is no worse**: the defect
> this ADR names, persisting for rows written before the fix and bounded by the backstop that was
> their only bound. **The one path by which it could outlive that bound is closed**: §2's reopen ends
> it before clearing the fence. **A cross-store migration read is refused**: `permissions` reading
> `PlanStore` at upgrade to find which goals are closed is the subsystem-boundary crossing §1 declines
> at the write, and declining it at the write while taking it at the upgrade would put the same read
> in the same place by another door. **No lane adds a back-fill, a reconciliation pass or a start-up
> scan for these rows.**

> **Normative — the arms the lane owes, and they are ten.**
>
> 1. **The ending over the set, the fence with it, and the record's version.** A goal holding
>    established rows for two declarations, one live and one lapsed, plus an unexpired `PROPOSED`
>    row and a row already `SUPERSEDED`: `end_for_goal` answers **3**, all three non-retired rows
>    stand `GOAL_CLOSED` carrying the call's own instant, and the `SUPERSEDED` row is
>    **byte-identical** to what it was. A **second** call answers **0** and leaves the fence set. A
>    goal the store holds no row of answers **0**, does not raise, **and is fenced all the same** —
>    asserted by a `record` refused afterwards. **And the record keeps the higher version**: a
>    second `end_for_goal` at a **higher** `goal_version` raises it — a `clear_closure` at the first
>    version then answers `False` and the fence **stands** — while one at a **lower** version leaves
>    it where it was, and neither moves a row. **And `clear_closure`'s own answer is asserted on
>    both paths §1 states it over**: against a fence standing at the version passed it answers
>    **`True`**, the fence is **lifted** — asserted by a `record` for that goal then succeeding —
>    and the **record stands** at that version, which a second `clear_closure` at the same version
>    shows by answering **`False`**; against a goal the store holds **no** record of it answers
>    **`False`**, writes none and raises nothing.
> 2. **Indivisibility, and the fence in the same step.** A `record` or a settlement to `ESTABLISHED`
>    raced against `end_for_goal` leaves the store in one of exactly two states — the write landed
>    **before** the call's step and the row is ended and counted, or it is **refused**, `record`
>    with `InvalidAuthorizationError` and the settlement with `NOT_AT_SOURCE` over a row the same
>    step ended. **What no interleaving produces** is a row of that goal standing `PROPOSED` or
>    `ESTABLISHED` after the call returns, nor a partition of the rows its step saw.
> 3. **The graph, `settle` and the retired member.** `ESTABLISHED → GOAL_CLOSED` and `PROPOSED →
>    GOAL_CLOSED` through `settle` → `SETTLED`; each call repeated → `NOT_AT_SOURCE`; **every** move
>    out of `GOAL_CLOSED` → `NOT_AT_SOURCE`, one test per target. A `GOAL_CLOSED` row is **never**
>    live, is absent from `standing`, and is present in `recent` and in `export` carrying its
>    coverage, its basis and its **unmoved** `expires_at`.
> 4. **The closing act, in order.** `abandon_goal` on a goal holding two established rows ends both
>    and **then** closes the goal; the act's answer is `ABANDONED` or `ABANDONED_EFFECT_IN_FLIGHT`
>    exactly as ADR-0261 §6 fixes it; an act answering `NO_SUCH_GOAL` or `ALREADY_CLOSED` from its
>    first read ends **nothing** and fences **nothing**; and a `StaleExecutionError` retry calls
>    `end_for_goal` **once per attempt it makes**, asserted over the call count — one whose re-read
>    finds the goal **closed** calls it once in the whole act, answers `ALREADY_CLOSED` and **leaves
>    the fence standing**; one whose re-read finds it **open** calls it a **second** time, under the
>    re-read version and before the retried write, so a **fresh** row a reopen admitted between the
>    attempts is ended `GOAL_CLOSED` with the rest. `clear_closure` is called **not at all** on
>    either path.
> 5. **`BLOCKED`, the reopen, and two reopens racing.** `set_goal_status(…, BLOCKED)` ends **no**
>    row, fences nothing, and the goal's rows still cover a later request. A reopen writes `ACTIVE`,
>    **then ends, then clears** — the three asserted in that order — after which a fresh row
>    records; the goal's `USER_STATED` constraints are **unchanged** across the closure and the
>    reopening; and of **two acts reopening one goal**, the one whose `ACTIVE` write is refused
>    stale calls **neither** member and retires **no** row the winner established. **And each act
>    overtaken by the other changes nothing, which is what the watermark is for.** A reopen
>    overtaken by a later closure: with the reopen's `ACTIVE` write landed and a closing act then
>    fencing at its own higher version, the reopen's delayed `clear_closure` answers `False`, the
>    fence **stands**, and a `record` for that goal is refused. And a closing act overtaken by a
>    reopen — a first closure fenced at its version, a reopen then lifting that fence at a higher
>    one, a **fresh** row recorded under the reopened goal — the first act's delayed `end_for_goal`
>    at its **own** version answers **`0`**, leaves that row `ESTABLISHED` and **live**, and leaves
>    the fence **lifted**, a `record` for that goal still succeeding.
> 6. **The trail and the recheck.** A route-(d) `ALLOW` whose row is ended `GOAL_CLOSED` between
>    `live_for` and `AuditTrail.record` is **refused** on ADR-0254 §7's disposition check, with no
>    conjunct added; and `decide` over a goal whose rows are all `GOAL_CLOSED` reaches route (d) in
>    no case, `live_for` answering `None`.
> 7. **Each half of the two-write sequence failing, injected, and the act compensating nothing.**
>    `end_for_goal` raising: the act propagates, **`PlanStore` is not called at all** — asserted
>    over the call count and not only over the stored state — no status is written, no attempt is
>    committed, **no fence stands**, and a re-run performs the act whole; **the same injection on
>    the retry attempt** leaves the first attempt's fence **standing** and no status written. The
>    **closing write** raising after a successful ending: the act propagates, the rows stand
>    `GOAL_CLOSED`, the goal is still open with its attempts untouched, **`clear_closure` is called
>    not at all** — asserted over the call count — **the fence stands**, and every later `record` of
>    that goal is refused. **And the goal is recoverable**: abandoning it succeeds and closes it,
>    and reopening it then leaves a goal a fresh row records under. **The order is asserted
>    directly** — `end_for_goal` strictly before the closing write on every path that takes both.
> 8. **A proposal across a closure and a reopen, which is what the fence is for.** An unexpired
>    `PROPOSED` row exists when the goal closes; it is ended `GOAL_CLOSED`; the goal is reopened and
>    the fence cleared; an answer naming that row then settles **nothing**, answering
>    `NOT_AT_SOURCE`, and **no call of the reopened goal is covered by it**. And across the closure
>    a `record` for that goal is refused, before and after the reopen's `ACTIVE` write and admitted
>    only after `clear_closure`. **That last admission is §8's booked residual and is asserted as
>    such rather than assumed absent**: a `record` begun before the closure and arriving after the
>    clear **succeeds**, which pins the state §8 declines to close exactly as arm 9 pins `clear`'s.
> 9. **`clear` erases the records with the rows, and the consequence is asserted rather than
>    avoided.** A goal is closed and then `clear()` runs: it answers the count of **rows** and the
>    store holds none — a goal whose fence a reopen had already lifted included, its record going
>    with the rest; a `record` for that closed goal afterwards **succeeds**, which is §1's universal
>    holding *absent a `clear`* and is the stated cost. `export` before the `clear` carries the
>    `GOAL_CLOSED` rows and **no fence**, ADR-0254 §16's snapshot being over rows.
> 10. **A database written before this decision, which is what prospectivity leaves.** A store at
>    the previous `schema_version` holding an `ESTABLISHED` row whose goal is **already closed**:
>    the upgrade ends **nothing**, records **no** closure and rewrites **no** row; the row still
>    appears in `standing` and still covers a call, **until its own `expires_at`** and no
>    longer — asserted by advancing the clock past it. **The reopen is the one path that is
>    closed**: reopening that goal ends the row `GOAL_CLOSED` before clearing the fence, so a
>    call of the reopened goal is covered by **no** row written before the upgrade. **And each
>    reopen call failing is injected, on both databases**: here `end_for_goal` raising after a
>    successful `ACTIVE` write leaves the goal **active and unfenced**, its legacy row **still
>    `ESTABLISHED` and still covering a call** until its own `expires_at`; on a goal closed
>    **under** this decision the same injection leaves it active and **fenced**, every `record`
>    refused; and on both, `clear_closure` raising leaves whatever the ending left and abandoning
>    then reopening recovers it.

### 10. This ADR classified, marked, and how it is ratified

**A reader acts differently, so this is a decision and not a clarification.** A reader holding the
corpus without it ships an authority that outlives the request it was granted for by up to a
deployment's whole retention window, and a listing that offers the user a live authority over a
finished booking. **It is a partial supersession of exactly three documents** (ADR-0070 §3) —
ADR-0254 in four scopes, ADR-0256 in one and ADR-0250 in one — and the `Status` line of each names
its scopes **without an `ADR-NNNN` token inside the parentheses**, so ADR-0070 §4's extraction
invariant holds. **The records land in the same change as this document** (ADR-0082 §7), and nothing
else in any of the three is edited — no Decision text is rewritten, which ADR-0070 §1 forbids.

**This ADR is marked** under ADR-0089 as ADR-0257 §1 widens the token: every obligation is a
normative blockquote at column 0 stating its own scope, unmarked text beside a mark supplies no
obligation of its own but settles what a mark means (§3), and quoted marks appear inside quotation
marks in running prose.

**It is a contract-surface change** — `core/types.py`'s `AuthorizationDisposition` gains a member
and **`core/protocols.py`'s `GoalAuthorizationStore` gains two** — so it owes **both** review lenses
on one tree, which ADR-0015 §1 makes true of a prose-only PR. **No new Protocol is added, so no
triad is owed**: both members land on a Protocol whose conformance suite and canonical fake already
exist and each gains its arms. **It merges as its own PR, ratified, before anything implements
against it** (golden rule 5); §9's lane is briefed after it merges, and the ratification flip is one
line and no other byte (ADR-0165).

## Consequences

**What becomes possible.** An authorisation can be said to be *for a request*, which is the sentence
the owner's ruling is written in and which the corpus could not previously express: a **closing
act** of a goal ends every authorization of it still standing, however the row came into being — the
ending is stated over the goal's rows and never over how one was written (§1) — on a database this
store closed the goal in, the three residuals below being where that rule stops. A user opening the
listing of a finished booking therefore sees no live authority, because they hold none. And the
campsite walkthrough M33 runs becomes checkable end to end — book, verify, close — rather than
ending with a standing authority nobody intended and nothing retires.

**What becomes harder, and the cost is paid in authorisation acts of its own.** On the path this
decision governs — a goal this store closed, outside the three residuals above — a request after a
closure inherits **no** authority from the request that ended and is covered only by an act taken
for it, including where the user experiences it as a small amendment: *"make it Sunday"* the day
after a confirmed booking is a fresh confirmation, and the only thing that stops it being a fresh
**money** question is §5's offer carrying the figure. A goal closed by mistake cannot have its
authority restored — the member is retired and the repair is the user's own answer, which is the
fail-closed direction and the same one ADR-0254 §1 takes for supersession. And a deployment that
closes goals eagerly asks more often than one that leaves them `ACTIVE`, which makes A10's
verification rule a lever on how often the user is interrupted — a coupling worth watching and one
nothing here can hide.

**What is disclosed rather than closed.** The ending is **two writes in two stores**, and the fence
is what makes the first of them total rather than best-effort: from the instant `end_for_goal`
returns, and for as long as the fence it raised stands, no row of that goal stands `PROPOSED` or
`ESTABLISHED` and none can be recorded, so the closing write cannot be raced. **The residuals
divide, and the division is the honest summary**: most cost a question, and three can leave an
authority.

**Those that cost a question.** A failure between the two writes leaves the goal open, its
authorities gone, its fence standing and every call of it asking until the user abandons and reopens
it — compensated by nothing and repaired by no sweep (§1, §8), because a compensation cannot tell an
orphaned fence from one a concurrent closing act is standing on. Between a reopen's `ACTIVE` write
and its `clear_closure` a turn is refused a row and asks. And where a closure under this decision
had run, a failure of either reopen call leaves that same open-and-fenced state with the same
repair. A call already claimed when its goal closes is ADR-0254 §13's residual window unchanged and
A9's to close — a **cross-store** race the fence does not reach and does not claim to.

**Those that can leave an authority, stated rather than rounded away.** On a **pre-decision
database** (§9) the ending is prospective: **no upgrade and no sweep** ends a row whose goal closed
before this decision, the reopen is the one path that does (§2), and a reopen whose `end_for_goal`
fails leaves the row `ESTABLISHED` and covering calls until its own `expires_at` — fail-**open**,
bounded by the retention window that was its only bound before, and no worse than what this decision
improves on. A **`record` begun before a closure and admitted after a reopen** has cleared the fence
writes a live row carrying an authority given for the ended request, which §8 books to A9 rather
than closing. And a **`clear`** erases the records with the rows, so a delayed write for a closed
goal afterwards succeeds — against a store the user has emptied of everything else, at their own
instruction. **None of the three is created here**: each is a state the corpus already reached,
narrowed rather than widened by this decision, and each is named with what would close it.

**These are the cases that would falsify the design.** A workflow in which the user genuinely
expects one authority to span several requests — a trip planned as five bookings under one budget —
which the goal-keyed row would make five questions, and which the standing grant §8 defers is the
answer to rather than this ending being wrong. A10 turning out to close goals far later than the
user considers the request finished, so the authority outlives it anyway and the ending buys
nothing. And an offer flow in which the figure is not available when the offer is composed, so §5's
*"not a separate money prompt"* fails not as a rule but for want of a quote — the practical
falsifier by a distance, and ADR-0267 §6's freshness disclosure is where it is already visible.

## Alternatives considered

**Shorten the row's `expires_at` when the goal closes.** Rejected. ADR-0254 §12's *"taken once, when
the row is written, and is never recomputed"* is what makes the instant the user was shown at the
act true afterwards, and an ending expressed by moving it would make the record say the authority
lapsed on a horizon nobody stated. A disposition says what happened; an edited instant says
something that did not.

**Reuse `EXPIRED`, or `REVOKED`.** Rejected on ADR-0254 §1's own reasoning, read one ending over:
re-using a member makes two different facts indistinguishable in a record whose whole purpose is to
say what the user authorised and what became of it. `REVOKED` would be worse than indistinguishable
— it would attribute to the user an act they did not take.

**Put the fence on the goal rather than in the authorization store.** Rejected: the refusal has to
be atomic with `record`, and a fact held in `PlanStore` could only be read across a subsystem
boundary before the write, which is the read-then-write this decision exists to close. The record is
in the store whose write it fences, which is the only place it can be.

**Make liveness depend on the goal's status, with no new member.** Rejected. `live_for` would have
to read the goal, which puts a `PlanStore` read on `ActionPolicy.decide`'s path across a subsystem
boundary — the shape ADR-0256 §6 declines for the closely related question of an act's own record,
*"machinery ADR-0254 §16's roster does not contain"* — and it would leave the row saying
`ESTABLISHED`, so the listing would still show an authority the policy would refuse.

**Read `standing(goal)` and settle each row, adding no store member.** Rejected for the window
between the read and the last settlement, for the partial failure — some rows ended, some not — and
because a loop can fence nothing: a row recorded after it has passed would stand under a closed goal
with nothing left to end it. One call in one step has none of the three.

**End the rows and leave the goal unfenced, disclosing the race as a residual.** Rejected, and it is
the shape two review rounds rejected with it. The decision's whole claim is that an authorisation is
ended by the act that closes its goal; a version of it that ends *the rows the closing act happened
to see* is a materially weaker decision, it makes §1's universal and §3's subordination of the
window both unsatisfiable, and it leaves a row of a finished request able to cover a call of the
same goal after a reopen. The fence is one record on one key in one store, refused against by one
member, and it buys the claim outright.

**Write the status first and end the rows after.** Rejected: its residual is an `ESTABLISHED` row
under a closed goal, which this decision exists to close and which it would reach on every closure
rather than in a booked residual, and ADR-0261 §2's live-attempt conjunct is stated over `ABANDONED`
alone, so an `ACHIEVED` goal may still carry a claimable attempt for it to cover.

**Leave the goal's `PROPOSED` rows standing and let the fence refuse the settlement.** Rejected, and
this is the alternative the `PROPOSED → GOAL_CLOSED` edge was chosen over. It is cheaper — one edge
instead of two, and a proposal is never live and authorises nothing, so nothing it leaves standing
can cover a call while the goal stays closed. What it costs is the claim: a row of the closed
request survives in a non-retired disposition, so *"no row written before the closure can ever cover
a call of the reopened goal"* stops being checkable over the store and becomes an argument about
what the fence refuses and when it was cleared — and after a reopen the fence is gone by
construction, leaving a stale answer to settle a proposal of the ended request against a bound the
user stated for it. Ending the rows makes the invariant readable off the rows themselves, which is
the property §1 is stated for.

**Compensate a failed closing write by clearing the fence.** Rejected, and it stood in an earlier
draft. The act cannot tell its own orphaned fence from one a concurrent act is standing on — two
acts whose first reads found the goal open share a version — so it can unfence a goal that did
close. §1 carries the reasoning and the cost accepted instead.
