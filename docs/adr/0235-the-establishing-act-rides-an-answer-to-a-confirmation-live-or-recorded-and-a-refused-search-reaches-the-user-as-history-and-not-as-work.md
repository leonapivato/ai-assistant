# 235. The establishing act rides an answer to a confirmation, live or recorded, and a refused search reaches the user as history and not as work

- Status: Proposed
- Date: 2026-09-04
- Decides: the establishing surface ADR-0193 §13 defers — which surfaces offer the
  act, where the act's `answer` comes from on each population it rides, what a
  surface shows before it collects one, how a recipient grant is listed and
  revoked, and what the user is told when a search was refused (ADR-0231 §19).
- **Partially supersedes** [ADR-0231](0231-the-planner-asks-for-a-search-the-turns-own-words-compose-it-and-the-results-come-back-as-records.md)
  — **§9's second clause, in its second limb alone.** That clause closes *"A
  recorded `CONFIRM` on a `WEB_SEARCH` decision **resolves in no turn**: no lane
  resumes it, offers it to an interface, or treats it as outstanding work, and §19
  defers the surface that would."* §3 below permits exactly one thing that limb
  forbids: such a decision may be **read from the trail and offered to a surface for
  the establishing act**. The other two limbs bind entire and §3 restates them — no
  lane resumes such a `CONFIRM`, and no lane treats it as outstanding work. §9's
  first, third, fourth and fifth clauses are untouched and load-bearing here: the
  servicer still asks nothing and parks nothing, the composing stage is still told
  nothing new, no lane weakens a declaration to reach an `ALLOW`, and the standing
  recipient grant is still the one route to one. §13 argues the classification and
  states the record ADR-0231's header is owed.
- Requires **new `core` contract surface** and lands none of it (§4, §12). Flagged
  under golden rule 5.
- Does **not** widen [ADR-0177](0177-the-browsers-control-surface-is-thirty-operations-and-a-credential-is-entered-only-on-a-loopback-origin.md)
  §1's operation enumeration (§9), does not designate a boundary, adds no condition
  to ADR-0017 §3's list, relaxes none, and attests that none is satisfied.

## Context

### Three deferrals converge here, and each names this decision

ADR-0193 built the standing recipient grant whole and deliberately stopped short of
the surface. Its §13 rules:

> No lane reads this ADR as deciding **which** surfaces offer the establishing act,
> what the wire carries for it, or how a browser or command-line surface lays it
> out. What §2 decides is that the act rides an answer to a recorded `CONFIRM`, what
> any surface offering it must show, and the one **operation** every such surface
> builds the grant with — `RecipientGrant.established_from` … The surfaces, and the
> revocation surface §9 assumes, are ADR-0177's, ADR-0178's and ADR-0186's to
> decide.

None of those three decided it. ADR-0177 §11 defers ADR-0148 §8's fourth clause and
makes it "a precondition on the implementing lane"; ADR-0178 §11 decides no
`core/protocols.py` surface and adds no `AssistantEngine` method; ADR-0186 §6 keeps
ADR-0177 §1's enumeration closed and assigns a browser view to "a **later consumer
lane** with its own ratified decision". So the deferral has been passed along three
times and lands here.

ADR-0231 §19 names it from the other side, as the condition on which its own
mechanism fires at all:

> **A surface for establishing a recipient grant.** The condition that makes this
> mechanism fire at all (§9). … Fired by those lanes. **Not** fired by this one.

and assigns this lane one further thing in terms:

> **Telling the user that a search was refused.** §9 gives the composing stage
> nothing, and a reply that said *"I would have searched but I am not permitted"* is
> a product surface with a user action behind it — which is the grant-establishing
> act, and therefore that lane's to design together with the message. Fired by that
> lane.

§8 below is that message.

### The tree, read rather than assumed

Every claim here was checked against `origin/main` at `6a49a318` while writing.

- **`RecipientGrant.established_from` has no caller.** Its only occurrences in
  `src/` are its own definition and three docstrings that name it; its only callers
  anywhere are the unit tests in `tests/core/test_recipient_grant.py`. Nothing in
  `orchestration/`, `interfaces/`, `app/`, `permissions/` or `wire/` invokes it.
- **The store is built and its two read faces are wired; nothing holds it whole.**
  `app/composition.py` constructs `SqliteRecipientGrantStore` and passes it as a
  `RecipientGrantResolution` to `SqliteAuditTrail` and as a `RecipientGrants` to
  `ThresholdActionPolicy`. Its own comment names the gap — *"and — once a surface
  offers the establishing act (ADR-0193 §13 defers which) — whole to whatever
  performs it"* — and the comment beside the policy states the consequence: *"until
  a surface offers the establishing act (§13) the store is empty, so every ruling is
  the one it was before."*
- **`AssistantEngine` carries no recipient-grant member.** Its `grant`, `revoke`,
  `recent_grants`, `standing_grants` and `grantable_sources` are all `SourceGrant`
  operations. `resume` takes `(token, *, approved, timeout)` and nothing else, so no
  argument on any promoted operation can carry the act.
- **The two confirmation surfaces render and cannot establish.**
  `interfaces/cli.py`'s `resume` drives `pending_confirmations`, renders each card
  and offers approve or decline; `assets/app.js`'s `renderConfirmation` offers
  `offerApproval` and nothing else. Neither has an affordance for making anything
  standing, and neither has an expiry field.
- **The policy already refuses the two unrecorded binding epochs at the resolving
  member.** `ActionPolicy.resolve`'s contract states that a `confirmed` whose
  `egress_binding` is an `OriginUnrecordedBinding` (ADR-0184 §7) or a
  `CoverageUnrecordedBinding` (ADR-0233 §14) "must not produce an `ALLOW`, whatever
  `approved` says". §3's act inherits both floors rather than restating them.
- **A confirmation is answered once, and the trail is what enforces it.**
  `SqliteAuditTrail._check_resolution` refuses a resolution where the trail already
  holds one naming the same `CONFIRM` — *"a confirmation answered repeatedly is one
  where a 'no' can be followed by a 'yes' until one sticks"* — and refuses one whose
  `tool`, `parameters_digest`, `step_id` or `execution_id` differs from the
  confirmation's, or which is timestamped before it.
- **The resuming path rebinds, and it needs the plan step to do it.**
  `StepRunner.resume` calls `_rebound` with the step's own `parameters` before it
  seeks a ruling (ADR-0152 §7), then builds the `ActionRequest` and records the
  resolving decision through `PermissionDecision.from_request`. A recorded decision
  alone carries no `parameters` — only a `parameters_digest` — so that route is
  unavailable to anything holding a trail row and nothing else.

Three claims a reader may have carried in from elsewhere do **not** hold, and are
stated here so that no clause below rests on one.

- **ADR-0177 §1's enumeration stands at thirty-one, not thirty.** ADR-0200 §12(a)
  partially superseded it, adding `converse_spoken`; ADR-0177's `Status` line and
  `wire/envelope.py`'s commentary both carry the figure. §9 below leaves it there.
- **There is no web search in the tree yet.** No `WebSearcher`, no `WEB_SEARCH`, no
  such `ReadKind` member; `ReadKind` is `SIGHTED_QUERY`, `CITATION_HOP` and
  `LOCAL_FILE`. The only artifact is the undriven HTTPS exchange in `tools/egress`,
  whose own docstring says *"Nothing constructs one yet."* Everything this ADR says
  about a `WEB_SEARCH` decision is said about ADR-0231's ratified text and about the
  lanes implementing it, not about code.
- **There is no `confirmations` command.** The command-line confirmation surface is
  `assistant resume` alone; `assistant grants`, `assistant granted` and
  `assistant revoke` are source-grant commands and §7 below keeps them so.

### Two populations, and the one respect in which they differ

ADR-0193 §2 fixes the act: a user **answering a recorded `CONFIRM` about an egress
call** and, in the same act, asking that that call's recipients be remembered. Two
populations of recorded `CONFIRM` exist, and they differ in exactly one respect —
whether an answer is already owed.

**(a) A confirmation a park holds.** A plan step sits `AWAITING_APPROVAL`, the turn
is suspended, `pending_confirmations` enumerates it, and `resume` is what answers it.
The answer both authorises the call and, under §2 below, may establish the grant. It
is outstanding work in every sense the corpus uses the phrase.

**(b) A confirmation no park holds.** ADR-0231's `WEB_SEARCH` decision is the whole
of this population today: it is not a `PlanStep`, reaches neither `StepExecutor` nor
`ExecutionState`, and therefore carries neither a `step_id` nor an `execution_id`.
Nothing waits on it, nothing resumes it, and the turn it belonged to composed and
finished. It is history.

The difference is what makes one door insufficient and two doors honest. Answering
(a) is an act on work; answering (b) is an act on a record. A single operation
covering both would have to call the second the first, which is the reading ADR-0231
§9 forbids, or call the first the second, which would put a second answer beside a
park that already has one.

### What this ADR is not allowed to settle

The grant record, its store, its coverage rule, its ceiling, its liveness and its
data rights are ADR-0193's and are consumed unchanged. Designation is ADR-0017 §2's
and ADR-0154 §1's. The request shapes, paths, framing and media types of any
gateway route are ADR-0168 §12's, not `core` surface and not this ADR's. Whether an
egress call may be **amended** while answering is ADR-0233 §10's and ADR-0193 §2's
seventh clause is what governs the act beside it. Nothing here re-opens #68's
disclose-onward property (ADR-0193 §10), #75, #1154 or #1551.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

The decision in one sentence: **the establishing act is a user answering a recorded
`CONFIRM` they have been shown in full and, in the same call, naming the instant
until which that call's recipients are remembered; it rides `resume` where a park
holds the confirmation and a second operation where none does; the second offers the
recorded decision as history and never as outstanding work; and a grant is listed and
revoked in a vocabulary of its own, on the terminal now and in a browser by that
lane's own decision.**

### 1. The act, and what is one call rather than two

> **Normative.** The establishing act is **one call on the promoted surface**, in
> which the user's answer to a recorded `CONFIRM` and the instant the grant ceases to
> be live are supplied together. No surface collects the answer in one call and the
> standing request in another, and no operation establishes a grant from an answer a
> previous call recorded. This is ADR-0193 §2's *"in the same act"* read as a
> contract: an act split across two calls is one a client can half-perform, and the
> half that survives is an approval the user believed was standing.

> **Normative.** Where the answer is going to be an `ALLOW`, both operations
> **refuse an expiry that is not strictly after the instant that will stamp that
> answer** — after the policy has ruled and **before that answer is recorded** — and
> the refusal names the instant it was compared against. `RecipientGrant` refuses a
> granting record whose `expires_at` is at or before its `decided_at` (ADR-0193 §9)
> and `decided_at` is the answer's, so an operation that did not check would record
> the answer and only then meet a construction refusal, leaving a decision in the
> trail, no grant, and a user told nothing they could act on. It is the shape §3's
> seventh condition closes one axis over, closed the same way and for the same
> reason: a precondition on the act is checked where the act is offered, not where
> the record is built. Where it refuses on `resume` the step stays durably parked and
> answerable, exactly as §2's binding refusal leaves it.

> **Normative.** That check is **scoped to the establishing path and reaches no other
> outcome**. Where the ruling is not an `ALLOW` — a declining answer on `resume`, or a
> policy that declines an approving one on either operation — the answer is recorded
> exactly as it would be had no expiry been supplied at all, the supplied instant is
> not consulted, and no grant is established. ADR-0042 §4's guarantee that
> `approved=False` yields a recorded `DENY`, and every obligation of
> `ActionPolicy.resolve`, are preserved whole; this ADR states no exception to either,
> and no clause of it suppresses the record of a decision the policy made.

> **Normative.** The instant compared against is **the one the operation will stamp
> on the answer**, chosen once and used for both. No operation reads the clock a
> second time between the comparison and the record, because two reads admit an
> expiry that passes the check and fails the constructor — which is the failure this
> clause exists to remove rather than to narrow.

> **Normative.** Every operation offering the act obtains its `RecipientGrant` from
> `RecipientGrant.established_from` and **mints none of its own**, which is ADR-0193
> §2's clause binding unchanged. Neither operation below builds a `RecipientGrant`
> field by field, and neither passes a granting record to
> `RecipientGrantStore.record` that `established_from` did not return.

> **Normative.** The instant the grant ceases to be live is **stated by the user and
> by nobody else**. No surface, adapter, gateway or engine defaults it, derives it,
> extends it, rounds it, offers it pre-filled, or supplies one where the user
> supplied none. ADR-0177 §1's fourth clause already says this of every argument
> expressing what the user asked for, and ADR-0193 §9's *"The user chooses the
> instant in the establishing act"* is what makes it this argument's rule too. A
> deployment-configured default lifetime is the `Settings` value ADR-0097 §8 refuses
> in the other direction: what may not be created by configuration may not be dated
> by it either.

> **Normative.** An act the user does not ask for is not performed. Approving a
> call and establishing nothing standing is the ordinary outcome and stays the
> default of every surface; the standing request is a separate thing the user
> supplies, never a state a control arrives in. No surface pre-selects it,
> pre-checks it, defaults it to true, presents it as the lower-effort path, or
> couples it to the approval control such that one act performs both (ADR-0233 §8's
> control clause, read on this second control).

### 2. Population (a): the answer to a held confirmation carries the act

> **Normative.** Where a park holds the confirmation, the act rides
> `AssistantEngine.resume` and no second operation. `resume` gains **one**
> keyword-only argument, `remember_recipients_until: UtcInstant | None = None`, and
> gains nothing else: no second argument, no widened return, and no change to
> `token`, `approved` or `timeout`.

> **Normative.** `remember_recipients_until` is honoured **only** where `approved` is
> true and the policy's resolving ruling is an `ALLOW`. Supplied beside
> `approved=False` it **establishes nothing and changes nothing else**: the answer is
> recorded as a `DENY` exactly as it is today, the step is denied, and no grant is
> written. ADR-0042 §4's guarantee that `approved=False` yields `DENY` is preserved
> whole and this ADR states no exception to it — a user who declines has *decided*,
> and an argument that could suppress the record of a decision would be the failure
> that obligation exists to prevent.

> **Normative.** `resume` **refuses the whole call, before any ruling is sought and
> before anything is recorded**, where `remember_recipients_until` is supplied,
> `approved` is true, and the confirmation's `egress_binding` is not an
> `EgressBinding` whose `planned_with_external_content` is `False` — the same two
> conditions §3's sixth and seventh place on the recorded population, on the held one.
> The step stays durably parked and answerable, no answer and no execution follow, and
> the user may answer again without the standing request. The clause is scoped to an
> approving answer because the clause above governs a declining one, and a refusal
> that suppressed a `DENY` would be the exception to ADR-0042 §4 this ADR does not
> state.

> **Normative.** The **asymmetry with the declining answer above is deliberate**, and
> it is stated so that no lane repairs it into consistency. A decline carries
> ADR-0042 §4's guarantee that the `DENY` is recorded, so the answer is recorded and
> the argument establishes nothing; an approving answer carries no such guarantee, the
> park survives a refusal, and the user may answer again. So the refusal costs a
> second call where recording would cost an egress call nobody can un-send, and
> fail-closed is available on one and forbidden on the other.

> **Normative.** That refusal takes the shape `StepRunner.resume` already uses for a
> binding it may not resume — refused by name before any ruling is sought, so nothing
> is written and the step stays parked (ADR-0184 §8's fourth clause, ADR-0233 §14). It
> is not a new mechanism and no lane builds one for it.

> **Normative.** **No surface offers the standing control beside a declining answer,
> and none offers it on a confirmation §3's sixth and seventh conditions exclude**
> (§5's rendering floor is what tells the surface which). Both shapes above are
> therefore unreachable from a conforming surface, and the clauses exist so that the
> Protocol has a defined answer for a client that sends one anyway. A surface that has
> collected a decline states, if it says anything at all, that a declined call
> establishes nothing (ADR-0193 §2) — never that the standing request was recorded,
> deferred, remembered or will be offered again.

> **Normative.** Where the policy answers a `DENY` to an `approved=True` resume —
> which `ActionPolicy.resolve`'s second obligation expressly permits — the `DENY` is
> recorded as it is today and **no grant is established**. The establishment fails
> with the ruling's own reason; nothing looser is minted in its place.

> **Normative.** `resume`'s existing behaviour is otherwise unchanged in every
> respect. A call supplying no `remember_recipients_until` behaves byte for byte as
> it does today, a restatement of a settled binding (ADR-0198 §§1–3) consults the
> argument no more than it consults `approved`, and no clause here makes a park
> answerable twice.

**One argument rather than a second operation, because the answer is the act.**
ADR-0193 §2's first clause makes the grant ride *an answer*, and a park has exactly
one answer (ADR-0044 §2b, enforced at `_check_resolution`). An operation that
established a grant from a park's already-recorded answer would be a second act on a
settled binding — reachable long after the user stopped looking at the call — and an
operation that answered the park itself would be `resume` under another name.

**And it is reachable from every surface `resume` already reaches, with no
enumeration to widen.** `resume` is one of ADR-0177 §1's operations and is reached
"with the arguments the promoted surface declares and with no others"; a newly
declared argument is admitted by that clause rather than by a change to it (§13).

### 3. Population (b): a recorded `CONFIRM` no park holds, offered as history

> **Normative.** `AssistantEngine` gains an operation that performs the act on a
> **recorded** `CONFIRM` no park holds:
> `establish_recipient_grant(decision_id: str, *, expires_at: UtcInstant) -> RecipientGrant`.
> It reads the named decision from the `AuditTrail`, obtains the resolving ruling
> from `ActionPolicy.resolve` with `approved=True`, and — where that ruling is an
> `ALLOW` and §1's expiry check passes — records that answer, builds the grant with
> `RecipientGrant.established_from`, records the grant, and returns it. The clauses
> below say what it does on every other outcome.

> **Normative.** It is available on a decision meeting **all seven** of the
> following, and is refused on any other: the trail holds it; its ruling is a
> `CONFIRM`; its `step_id` **and** its `execution_id` are both unset; the trail holds
> no decision resolving it; its `expires_at` is unset or is strictly after the
> instant of the call (ADR-0059 §1); its `egress_binding` is an `EgressBinding` —
> never `None`, never an `OriginUnrecordedBinding`, never a
> `CoverageUnrecordedBinding`; and that binding's `planned_with_external_content` is
> `False`.

> **Normative.** The third condition is the one that keeps the two populations apart,
> and it is **structural rather than a rule to remember**. A confirmation carrying a
> `step_id` or an `execution_id` belongs to a step of an execution; its answer is the
> resuming one, which rebinds the call before it seeks a ruling (ADR-0152 §7) and
> which §2 above is the only door to. No lane relaxes this condition, and no lane
> reaches this operation from a park by clearing either field.

> **Normative.** The sixth condition is stated over the binding's **type** and is
> refused at this operation rather than inherited. `ActionPolicy.resolve` already
> returns no `ALLOW` on either unrecorded epoch (ADR-0184 §7, ADR-0233 §14), so the
> act could not complete in any case; refusing before the trail is asked keeps the
> act from being offered on a row it can never ride, and keeps this operation's
> answer to *"may I establish from this?"* decidable from the row alone.

> **Normative.** The seventh condition is ADR-0193 §2's third clause read at this
> surface, and it is **refused here rather than left to the constructor** because the
> constructor runs too late. `ActionPolicy.resolve` returns an `ALLOW` on an approved
> confirmation carrying `planned_with_external_content` — ADR-0181 §5's fourth clause
> requires only that `approved` be true — so an operation that checked nothing would
> record the answer and *then* meet `established_from`'s refusal, leaving an `ALLOW`
> in the trail, no grant, and a user told nothing they could act on. A user answering
> such a confirmation may approve the call; they may not, in that act, make the
> recipients standing (ADR-0193 §2, §4), and the surface must know that before it
> offers the act rather than after it has collected one.

> **Normative.** Where `ActionPolicy.resolve` answers other than an `ALLOW` on
> `establish_recipient_grant` — which its second obligation expressly permits for a
> confirmation answered long after it was asked — **that answer is recorded** and the
> operation raises, establishing nothing. Suppressing it would be the failure
> ADR-0042 §4's guarantee exists to prevent, read one operation over: the policy
> ruled on a question the user answered, and a ruling the trail never sees is a
> decision nobody can audit. Because a confirmation has one answer (ADR-0044 §2b) the
> decision is thereby settled, and §3's fourth condition then keeps the act from being
> offered on it again — which is stated here rather than discovered, since it is the
> one outcome on this population that costs the user the act.

> **Normative.** The operation **resumes nothing and services nothing**. The
> `ALLOW` it records authorises a call that has already been abandoned: no lane
> executes it, re-composes the turn it belonged to, re-plans, re-services a read, or
> treats the recorded answer as making anything runnable. ADR-0231 §9's first limb —
> *"no lane resumes it"* — binds entire, and ADR-0231 §9's first clause is unmoved:
> a `WEB_SEARCH` request is serviced only on a recorded `ALLOW`, and a servicing
> happens inside the turn that asked, which this one is not.

> **Normative.** No component treats a decision this operation could ride as
> **outstanding work**. It is not returned by `pending_confirmations`, is not a park,
> holds no turn, blocks nothing, expires under no sweep, is reclaimed by nothing, and
> is presented by no surface as a task, a queue, a to-do, a badge, an unread count,
> an alert, or anything a reader could take as owed. ADR-0231 §9's third limb binds
> entire and this clause is what makes it checkable at a surface. What §3 permits is
> only that the recorded decision be **read and offered**, which is the second limb
> and the whole of what this ADR supersedes.

> **Normative.** `AssistantEngine` gains the read that makes the act reachable
> without a surface joining trail rows for itself:
> `grantable_decisions(*, limit: int = DEFAULT_PAGE_SIZE) -> tuple[PermissionDecision, ...]`.
> It returns, most recent first under ADR-0186 §2's order, those of the trail's most
> recent `limit` decisions that meet **every** condition above. A non-positive
> `limit` raises `ValueError` rather than being clamped or passed through, for the
> reason ADR-0021 §4 gives and ADR-0186 §3 restates.

> **Normative.** `limit` bounds the **rows read** and therefore also the rows
> returned, so a grantable decision older than the window is not offered and the
> operation makes no unbounded read of a Tier 1 store. The recourse is a larger
> `limit`, which is `assistant decisions --limit`'s own shape. This ADR mints no
> filtered, indexed or per-kind read of the trail and adds no member to `AuditTrail`
> (§11).

> **Normative.** A decision is offered only where the window read is **complete for
> it** — which holds when the read returned fewer rows than `limit`, and otherwise
> when that decision's `decided_at` is **strictly after** the `decided_at` of the
> oldest row the read returned. A decision at that boundary instant is **not
> offered**, whatever else it satisfies, and the recourse is a larger `limit`.

> **Normative.** That rule is what makes the fourth availability condition —
> "the trail holds no decision resolving it" — decidable from the window, and it is
> stated rather than left to an implementation because the naive reading is wrong. It
> rests on two clauses of the `AuditTrail` contract and on nothing else: `record`
> refuses a resolution whose confirmation "was decided *after* the resolution
> answering it", so a resolution's `decided_at` is at or after its confirmation's,
> **equal timestamps included**; and `recent` returns the newest rows ordered by
> `decided_at` descending, ties broken by `id` ascending. Every row strictly newer
> than the oldest returned is therefore inside the window, so a candidate strictly
> newer than the boundary has any resolution of it inside the window too — while a
> candidate sharing the boundary instant may have one tie-broken just outside it, and
> offering that one would be offering a confirmation the user has already answered.

> **Normative.** The engine **composes no answer of its own** on either operation.
> `ActionPolicy.resolve` authors every ruling, the trail records it, `core`
> transcribes the grant, and the store admits it; the engine sequences those four and
> supplies the ids and instants a caller that records supplies (ADR-0193 §1). It
> reaches no `RecipientGrants` query face, evaluates no coverage, and reads no
> `authorised_by`.

**Why this population needs a second door at all, argued rather than assumed.**
ADR-0231 §9 is explicit that a `WEB_SEARCH` `CONFIRM` "resolves in no turn", and its
Alternatives refuse both repairs that would have made `resume` reach it: *parking the
turn on a read* would put a durable confirmation and a resume path behind a mechanism
ADR-0226 §5 designed to be invisible, and *recording a pending confirmation for the
user to answer later* "invents an outstanding-work concept the corpus has nowhere to
put and that nothing would resolve". Both stand. What this ADR adds is neither: the
decision is already recorded, in a store the user already reads through
`recent_decisions`, and what is new is an act on that record.

**An `ALLOW` that authorises nothing that runs is a state this corpus already has,
and saying so is cheaper than inventing a fourth outcome.** ADR-0193 §9 describes a
recorded `ALLOW` overtaken by a revocation an instant later — *"still appended, and
may still be executed"* — so nothing in the corpus reads a recorded `ALLOW` as a
claim that the call ran; the invocation record that would say so is ADR-0192's
separate row. §5's disclosure clause is what keeps the user from reading it as one.

**The alternative of composing a fresh confirmation about a probe call was
available and is refused by name.** ADR-0193 §2's second clause forbids any
out-of-call establishment, and its commentary says why a surface that assembled a
call-shaped question for the purpose would be *"rendering a fabricated call-level
fact, which is the unobtainable bound ADR-0098 §6's second clause forbids"*. A probe
would also put a user-typed provider string where ADR-0148 §2's canonicaliser has to
meet it, reopening from the surface a question the seam has closed.

### 4. The `core` surface: five engine members, one argument, one transcribing constructor

> **Normative.** This ADR decides the following `core` surface and lands none of it.
> A contract that adds a member, widens an argument or changes a return is changing
> this decision rather than implementing it. The block is display, not a mark
> (ADR-0089 §2); the clauses around it are the obligations.

```python
class AssistantEngine(Protocol):                       # core/protocols.py
    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,
        remember_recipients_until: UtcInstant | None = None,   # §2
    ) -> TurnOutcome: ...

    async def grantable_decisions(                             # §3
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[PermissionDecision, ...]: ...

    async def establish_recipient_grant(                       # §3
        self, decision_id: str, *, expires_at: UtcInstant
    ) -> RecipientGrant: ...

    async def standing_recipient_grants(                       # §7
        self,
    ) -> tuple[RecipientGrant, ...]: ...

    async def recent_recipient_grants(                         # §7
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[RecipientGrant, ...]: ...

    async def revoke_recipient_grant(                          # §7
        self, grant_id: str
    ) -> RecipientGrant | None: ...


class PermissionDecision(BaseModel):                   # core/types.py
    @classmethod
    def from_confirmation(                                     # §4
        cls,
        confirmed: PermissionDecision,
        ruling: PermissionRuling,
        *,
        id: DurableIdentifier,
        decided_at: UtcInstant,
    ) -> PermissionDecision: ...
```

> **Normative.** `PermissionDecision.from_confirmation` is a **pure transcribing
> constructor** on the record in `ai_assistant.core.types`, and it is
> `from_request`'s shape for the same reason: everything describing *what was ruled
> on* is copied by `core` rather than asserted by whoever collected the act. It reads
> no clock, no store and no seam, and performs no I/O. It transcribes `tool`,
> `parameters_digest`, `egress_binding`, `step_id` and `execution_id` from
> `confirmed` by value; it sets `resolves` to `confirmed.id`; it takes the ruling
> from its caller and the `id` and `decided_at` a caller that records supplies; and
> it sets `expires_at` to `None`, which is the only value the record's existing
> lifetime validator admits on a decision that is not a `CONFIRM`.

> **Normative.** It **accepts no `tool`, no `parameters_digest`, no `egress_binding`,
> no `step_id`, no `execution_id` and no `resolves` from its caller**, so a caller
> has no parameter through which to substitute a subject or point the answer at a
> different question. That removes the capability rather than forbidding it, which is
> ADR-0021 §3's move and ADR-0193 §2's after it.

> **Normative.** It **refuses**, raising `ValueError`, where `confirmed`'s ruling was
> not a `CONFIRM`; where `confirmed` carries a `step_id` or an `execution_id`; and
> where `decided_at` is before `confirmed.decided_at`. The record's own validators
> then apply unchanged — a resolving decision whose ruling is itself a `CONFIRM` is
> already unconstructable, and a lifetime belongs only to an open question.

> **Normative.** The second refusal is what keeps `from_confirmation` off every path
> that **executes** a call. A confirmation carrying either field belongs to a step of
> an execution and its answer must be built from a rebound request through
> `from_request` (ADR-0152 §7, ADR-0148 §1); a confirmation carrying neither belongs
> to no step, so there is nothing to rebind and nothing to run. No lane relaxes it,
> and no lane routes a resuming answer through this constructor.

> **Normative.** `from_confirmation` lives on `PermissionDecision` and **nowhere
> else**. No lane moves it into `permissions/`, `orchestration/` or `interfaces/`,
> and none adds a second construction path beside it. It authors no ruling: the
> `PermissionRuling` it is handed comes from `ActionPolicy.resolve` and from nothing
> else, so ADR-0021 §3's split — only a policy may author a ruling — is untouched.

> **Normative.** This ADR adds **no Protocol**, no member to `ActionPolicy`,
> `AuditTrail`, `EgressBinder`, `RecipientGrants`, `RecipientGrantResolution` or
> `RecipientGrantStore`, no `Settings` field, no error class, and no member to
> `RoutableOperation`. The three grant faces are consumed exactly as ADR-0193 §1
> shipped them, and the engine holds the **store** face — which is what ADR-0193 §1
> withholds from the policy and from the trail and withholds from no one else, and
> what `app/composition.py`'s comment already anticipates passing *"whole to whatever
> performs it"*.

> **Normative.** No `interfaces/` adapter holds a `RecipientGrantStore`, a
> `RecipientGrants`, a `RecipientGrantResolution` or an `AuditTrail`. A surface is
> given records by the operations above and reads no store, which is golden rule 3
> and ADR-0193 §11's second clause read one operation over: a renderer given the
> store face would hold `record` and `clear`, and a remote client could not perform
> the read at all.

> **Normative.** Every new operation is cancellable under `core/protocols.py`'s
> cancellation clause (ADR-0060), observes no caller-owned container (ADR-0065), and
> returns a **detached snapshot** — the tuple, the records in it, and everything
> mutable those reach (ADR-0018 §3), as every neighbouring promoted read does.

**This is the smallest set that makes the act, the discovery, the standing answer
and the revocation reachable, and each member is here because a surface cannot
obtain it otherwise.** Without `grantable_decisions` an adapter would have to read
`recent_decisions` and join rows to find which confirmations are unanswered, which
is business logic in `interfaces/`. Without `standing_recipient_grants` there is no
surface that shows the user what they currently authorise, and ADR-0193 §9's
revocation right — *"a user may revoke a grant from any surface that shows them
their grants"* — has nowhere to sit. Without `recent_recipient_grants` an expired
grant occupies a slot against the ceiling and appears in no listing, so §6's stated
recourse names an act the user cannot perform. Without `revoke_recipient_grant` the
only exit from a grant is `clear` on a store no surface holds. And `from_confirmation` exists because the
resuming constructor needs a request no trail row can supply.

**`from_confirmation` was the alternative to widening `established_from`, and it is
the narrower change.** ADR-0193 §2 enumerates `established_from`'s refusals as a
marked clause; adding one there would amend that clause. What this ADR needed was
not a different grant constructor but a way to author the *answer* the existing one
already requires, and that is a decision constructor rather than a grant one.

### 5. What a surface shows before it collects the act

> **Normative.** ADR-0193 §2's rendering floor binds every surface offering the act,
> on both populations, unchanged and in full: the connected account's identity; the
> canonical destination set in **both** supplied and canonical forms; the payload
> description; the tool the grant is about, by the declaration's own identifier and
> capability, read from the declaration and never from a registry; the instant the
> grant ceases to be live; and a statement that calls this grant covers will **not**
> be put to the user, so the payload description of those calls is not shown again.
> Every value is inserted as data, neutralised for that target on render (ADR-0042
> §4).

> **Normative.** The surface renders `planned_with_external_content` under ADR-0181
> §6, in all its states, unchanged and in full, and renders no state of it as a
> detection, a score, or a warning that the call was malicious (ADR-0181 §7,
> ADR-0193 §2).

> **Normative.** On population (a) the surface is rendering a `Confirmation` whose
> `egress` is present, so ADR-0178 §7's floor and ADR-0233 §8's floor bind it whole
> and this ADR reduces neither. The span values are rendered before the answer is
> collected, whole, beside the description and never in place of any part of it; a
> surface that cannot render a value whole renders **no** confirmation and offers no
> act on it.

> **Normative.** On population (b) the surface is rendering a recorded
> `PermissionDecision` and not a `Confirmation`, so ADR-0186 §7's row floor binds it
> and ADR-0186 §8's bars bind with it. **ADR-0193 §2's floor above is met whole** —
> the account, both destination forms, the canonical destination set as `core`
> derived it, the payload description, the declaration and the origin are all on the
> binding the row carries (ADR-0148 §6, ADR-0150 §1) — which is what the act needs,
> because a grant reaches the recipient and never the payload (ADR-0193 §3, §5).

> **Normative.** **ADR-0233 §8's span-value floor is not met on population (b), and
> no surface claims it is.** That floor is stated over a surface rendering a
> `Confirmation` whose `egress` is present, which this is not, and the recorded
> decision carries a `parameters_digest` rather than the argument values, so the
> bytes are not in the store to render. No surface renders a digest as a value,
> renders a reconstruction, summary, excerpt or paraphrase of the arguments, or
> states or implies that the user has been shown what the call would have sent. A
> surface that cannot say what a call would send says so, which is the direction
> ADR-0233 §8's own no-summary clause fixes for the case where it can.

> **Normative.** A surface offering the act on population (b) states, before it
> collects it, **three facts about the call the user is deciding on**: that the call
> was refused and was not made; that answering now does not make it, and nothing is
> sent on account of the answer; and that what the answer establishes is a standing
> authorisation for the **recipients** of calls like it, never for their payloads
> (ADR-0193 §3, §5). It states them as facts about this record, and it names no
> future call, no expected benefit and no behaviour it cannot promise.

> **Normative.** No surface offers the act attached to an **edit** of the call it is
> about. ADR-0193 §2's seventh clause binds unchanged on both populations: a user who
> amends a call is issuing a new request, and no grant or answer carries across the
> amendment.

**The asymmetry between the two populations is stated rather than smoothed over,
because it is the honest one.** On (a) the user sees the bytes; on (b) they see the
record of a call whose bytes the trail deliberately does not keep (ADR-0021 §1's
digest binds the payload without storing it). What (b) authorises is unaffected by
that — a grant reaches the recipient and never the payload, and the recipients *are*
on the row, both forms, as `core` derived them. A surface that papered over the
difference by reconstructing arguments would be showing the user something no store
holds.

### 6. The order of the two records, and where the ceiling is enforced

> **Normative.** The **answer is recorded before the grant is**, on both populations,
> which is ADR-0193 §2's clause binding unchanged: the decision passed to
> `established_from` as `answer` is one `AuditTrail.record` has accepted, and the
> grant is recorded after it through `RecipientGrantStore.record`.

> **Normative.** An answer the trail **refuses** leaves no grant. Nothing is written
> to the grant store on a resolution the trail declined, and no surface reports the
> act as performed.

> **Normative.** The ceiling is enforced **where ADR-0193 §1 puts it and nowhere
> else** — inside `RecipientGrantStore.record`, atomically, counted over outstanding
> granting records. This ADR mandates **no pre-write count**, and the reason is that
> the declared store surface supplies none: `standing()` answers over **live**
> records and so undercounts an outstanding set that includes expired ones,
> `recent(limit)` is bounded and carries revoking records too, `outstanding(grant_id)`
> answers about one id, and `export()` is the unbounded read ADR-0193 §1 expressly
> declines to bound. A mandated pre-read would therefore either widen ADR-0193 §1's
> exact surface or make every establishing act perform an unbounded read of a Tier 1
> store, and neither is a price this decision pays for a check that could not be
> authoritative anyway.

> **Normative.** **No lane substitutes a live count for the outstanding count**, at
> the engine, at a surface, or in a store implementation's own fast path. The two
> differ by exactly the expired-but-unrevoked records ADR-0193 §1 says still occupy a
> slot, so a check over the live set passes acts the store will refuse and would
> report the wrong reason for the refusal when it came.

> **Normative.** Where `record` refuses on the ceiling, the operation **raises with
> the store's own `InvalidRecipientGrantError`**, and it returns no value a caller
> could mistake for an established grant. The answer stays recorded — the trail is
> append-only and nothing retracts it — and nothing already recorded in the grant
> store is removed, narrowed, expired, evicted or truncated to make room, and no
> looser grant is minted in its place (ADR-0193 §1, §2).

> **Normative.** A surface offering the act **states that refusal to the user at the
> moment it happens**, naming that the ceiling was reached and that the recourse is
> to revoke a grant they hold, and **not** presenting it as a fault of the call that
> was confirmed. That is ADR-0193 §1's clause discharged in the words it uses; what
> that clause forbids is offering the act and then **dropping** it, and a refusal the
> user is shown, named and given a recourse for is not dropped. Its own next
> sentence is what the outcome then is: *"The confirmation itself is unaffected — the
> user may still approve **that** call; what they cannot do is make it standing."*

> **Normative.** On population (a) that leaves a call approved and executed under a
> route-(a) answer, which is the outcome the user asked for minus the standing part.
> On population (b) it leaves an `ALLOW` that authorises nothing and established
> nothing. Neither is repaired by retrying with a different expiry, by narrowing the
> destination set, or by any of the moves the clause above forbids; the recourse is
> the revocation §7 makes reachable, after which the act may be performed again.

> **Normative.** No lane makes the two writes one transaction, coordinates the two
> stores, or claims an ordering stronger than the one stated here. ADR-0193 §9
> declines the cross-store linearisation for revocation and ADR-0007 §4 holds the
> erasure coordinator; this decision inherits both refusals and invents neither.

### 7. Listing and revocation: a second vocabulary, and why not one

> **Normative.** `AssistantEngine` gains three members here.
> `standing_recipient_grants()` reads `RecipientGrantStore.standing` — every **live**
> grant, evaluated by the store against one clock read (ADR-0193 §1, §9).
> `recent_recipient_grants(*, limit: int = DEFAULT_PAGE_SIZE)` reads
> `RecipientGrantStore.recent` — the store's own history, granting and revoking
> records alike, in its own order, with a non-positive `limit` raising `ValueError`.
> `revoke_recipient_grant(grant_id)` appends a revoking record naming the grant and
> returns it, or returns `None` where the store holds no outstanding granting record
> with that id. None of the three composes, filters, projects, enriches or summarises
> what the store returns, and none reads any other store.

> **Normative.** `recent_recipient_grants` is what makes ADR-0193 §1's stated
> recourse reachable, and it is here for that reason rather than for completeness.
> The ceiling counts **outstanding** granting records, which includes expired ones;
> `standing_recipient_grants` correctly omits those, because it states what the user
> currently authorises. Without a history read a user at the ceiling could hold an
> expired grant occupying a slot, see it in no listing, and have no id to pass to
> `revoke_recipient_grant` — so ADR-0193 §1's *"the recourse is to revoke a grant
> they hold"* and ADR-0193 §9's *"a user may revoke a grant from any surface that
> shows them their grants"* would both be undischarged.

> **Normative.** `recent_recipient_grants` is bounded by its `limit` and states no
> liveness. A grant older than the window is not in it and the recourse is a larger
> `limit`, which is `assistant grants --limit`'s own shape one store over; this ADR
> mints no complete read of the store for a surface (§11), and `revoke_recipient_grant`
> is what authoritatively answers whether a record is still outstanding.

> **Normative.** The revoking record is built by the engine from the outstanding
> record the store holds, transcribing its `tool`, `account` and `destinations` by
> value, with the engine supplying the record's own `id` and instants as a caller
> that records supplies them (ADR-0193 §1). Revocation is **whole**: no operation
> narrows a grant, re-scopes one, extends one, or edits one in place.

> **Normative.** Revocation is **never refused for the ceiling**, whatever the
> outstanding count, which is ADR-0193 §1's clause read at the surface that performs
> it: a ceiling that could block a revocation would trap a user above it with no way
> down.

> **Normative.** Recipient grants and source grants are **two vocabularies and never
> one**. No operation, command, route, view or listing answers one with the other,
> presents a recipient grant among source grants or the reverse, offers a control
> that revokes across both, or names a combined total. `grant`, `revoke`,
> `recent_grants`, `standing_grants` and `grantable_sources` stay `SourceGrant`
> operations and gain nothing; the command-line `assistant grants`,
> `assistant granted`, `assistant grant`, `assistant amend` and `assistant revoke`
> stay source-grant commands and gain no recipient argument.

> **Normative.** A surface may put the two on one screen. What it may not do is
> answer either question with the other's records, or present a control on one as
> acting on both — which is ADR-0177 §6's fourth clause read across a different pair
> and for its reason: a page that shows two things at once is the layout that invites
> one answer to be read off the other.

> **Normative.** No surface derives liveness from `recent_recipient_grants` or from
> an audit row. A record that listing carries says an **act happened**, never that it
> still stands; a revoking record in it is the record of a withdrawal and never a
> live grant (ADR-0193 §9). `standing_recipient_grants` is what states what the user
> currently authorises, and a view that has not read it says the state is unread
> (ADR-0177 §6's fifth clause, read one store over).

**Two vocabularies because the two authorisations are two things the corpus keeps
apart at every other seam.** ADR-0097 §7 forbids a source grant from ever being cited
as `PermissionRuling.authorised_by` and forbids any `ActionPolicy` from consulting a
source-grant seam; ADR-0193 §13 restates that verbatim; ADR-0186 §10 makes the same
move for the two trails — *"The two trails **partition** the subject and neither
answers the other's half"*. Their **acts** differ too: a source grant is established
from a list of sources and has no expiry, and a recipient grant can be established
only from a confirmation about a real call and must carry one. One noun over two
records that cannot substitute for each other is how a user comes to believe that
revoking one revoked the other.

**Naming.** `standing_recipient_grants`, `recent_recipient_grants` and
`revoke_recipient_grant` qualify the existing nouns because on this Protocol "grant" already has a referent and it is
`SourceGrant`; ADR-0186 §1's naming rule — that the shorter name is right only where
the word has one referent on the surface — comes out the other way here.
`grantable_decisions` names what it returns, follows `grantable_sources`' adjective,
and deliberately does **not** say "confirmations": `pending_confirmations` returns
`Confirmation`s and names outstanding work, and the collision is precisely where §3's
distinction has to be sharpest.

### 8. Telling the user a search was refused

> **Normative.** The message that a search was refused is `grantable_decisions`'
> listing and the act offered beside it, on the surfaces §9 admits, and is **nowhere
> else**. ADR-0231 §9's third clause binds unchanged: the composing stage is told
> nothing, and the assembled prompt on a turn whose search was refused stays
> byte-identical to what it would be had the planner asked for nothing. No lane puts
> the message in a reply, appends it to one, degrades one for it, or reads ADR-0228
> §10's carrier as covering it.

> **Normative.** It is **not a notification**. No lane mints a `Notification`, a
> notification kind, a delivery or a poll result for a refused search on the strength
> of this ADR; a notification is a decision about interrupting the user and this ADR
> takes none.

> **Normative.** The listing states what the recorded decisions say and no more,
> under §5's floor. It does not state that the turn would have answered differently,
> that a reply was incomplete, that a search would have succeeded, or that anything
> is owed — which is §3's outstanding-work clause read on the words as well as on the
> shape.

**A pull rather than a push, and that is the decision rather than a deferral.** The
alternatives were a sentence in the reply, which ADR-0231 §9's third clause forbids
and which this ADR does not disturb; a notification, which would make a refused read
interrupt the user and is the posture ADR-0226 §5 designed the mechanism against; and
saying nothing at all, which would leave ADR-0231 §19's assignment undischarged. What
is left is a place the user can look, next to the one act that changes the answer —
which is what "a product surface with a user action behind it" describes.

### 9. Per channel: the terminal now, the browser by its own decision, voice withheld

> **Normative.** The **command-line surface** carries all of it, and is the surface
> the implementing lane ships. `assistant resume` gains a way to state the instant
> beside its answer under §2, offered only where the confirmation is one an act may
> ride and never as a default or a pre-selection. **Four** commands are added,
> named in a recipient vocabulary distinct from the source-grant commands §7 keeps:
> the `grantable_decisions` listing with the act beside it; the standing listing;
> the bounded history over `recent_recipient_grants`, taking a `--limit` with the
> refusal §7 states; and the revocation, taking the id either listing renders.

> **Normative.** The history command is what makes ADR-0193 §1's recourse performable
> on the shipping surface, so it is named here rather than left to the lane: a user
> whose act §6 refused on the ceiling reaches it, finds the expired grant the standing
> listing correctly omits, and revokes. A lane that shipped the other three would ship
> a refusal whose stated recourse has no command behind it.

> **Normative.** The `--yes` flag, which today declines to answer any confirmation
> carrying an egress, **never supplies the act**. No non-interactive flag,
> environment variable, configuration value or scripted default establishes a grant:
> the act is a decision of the user made while looking at the call, and a flag that
> made it standing would be the out-of-call establishment ADR-0193 §2's second clause
> refuses, wearing a terminal's clothes.

> **Normative.** The **browser** is not reached by this decision. ADR-0177 §1's
> enumeration is not widened, none of §4's new operations resolves from a browser
> request, no browser argument reaches one, and the gateway makes no call of its own
> to any of them. `resume` stays in the enumeration and its new argument is admitted
> by ADR-0177 §1's fourth clause; whether the page offers a control for it is the
> browser lane's, and until that lane the page renders the card exactly as it does
> today.

> **Normative.** A browser surface for this act is a **later consumer lane with its
> own ratified decision**, which widens ADR-0177 §1's enumeration in its own text —
> the route ADR-0177 §1's third clause fixes for `learn` and ADR-0175 §6's third
> clause fixes generally. It inherits §5's floor, §7's two-vocabulary rule and §8's
> bars without restating them, and it owes ADR-0233 §8's whole-value floor on the
> card it edits.

> **Normative.** This ADR states the posture ADR-0199 §3's sixth clause obliges it to
> state, for the content these surfaces render: a canonical destination set, a
> connected account identity, a payload description, and any rendering, excerpt,
> summary or paraphrase of one, are **withheld** from a channel of unbounded
> audience. They are placed as speakable on no such channel, by this ADR or by any
> silence in it.

> **Normative.** **No spoken establishing surface is created, and none may be created
> by reading this ADR.** ADR-0207 §2's fixed sentence — `I need you to confirm
> something on your screen.` — remains the whole of what a live confirmation park
> says on `converse_spoken`, and no spoken form of the act, the listing or the
> revocation is minted. A standing recipient grant is established on a screen or it
> is not established.

> **Normative.** An ADR that admits a spoken or otherwise audible channel whose
> audience is **bounded** decides in its own text whether this content is placed as
> speakable there, on ADR-0199 §5's terms and its own. This ADR neither places it nor
> forecloses that ADR.

**The browser is deferred rather than refused, and ADR-0186 §6 is the precedent in
terms.** That section kept the enumeration closed for exactly this reason —
sequencing, not doubt: the terminal is where a milestone's exit can be measured with
no gateway in the loop, and "a history view landing beside that work would collide
with it in the same assets for no gain this milestone can measure". The confirmation
card in `assets/app.js` is under active change for ADR-0233 §8's floor, and this act
adds a second control and an instant field to that same card.

**Withholding voice costs something real and it is stated rather than minimised.** In
a deployment whose only surface is voice, a user cannot make anything standing and
every send is confirmed one call at a time — which is ADR-0207's existing behaviour
applied to a new case rather than a new restriction. The alternative, a spoken
recipient list, discloses the owner's correspondents into a room for whoever else is
in it, which is the disclosure ADR-0199 exists to refuse.

### 10. `PROTOCOL_VERSION`, and the number this ADR does not fix

> **Normative.** The lane implementing §4 moves `PROTOCOL_VERSION`, in the same
> change, and records the ground in the constant's own commentary as every prior move
> has. ADR-0124 §9's first limb is what obliges it: the promoted method set grows by
> **five** — the members §4's block declares — and `resume`'s declared arguments grow
> by one, so a peer at the earlier version and a peer at the later one do not agree
> about the surface.

> **Normative.** This ADR **fixes no number**, and that is deliberate rather than an
> omission. `PROTOCOL_VERSION` stands at 29 on `origin/main` and ADR-0231 §16 obliges
> a further move for `ReadKind.WEB_SEARCH` from a lane in flight beside this one; a
> number written here would be a fact about a tree that has since moved. The lane
> reads the constant and moves it by one, and no lane reads this clause as licence to
> skip the move or to fold two grounds into one entry.

> **Normative.** Nothing else under `wire/` changes for it. The connect exchange
> gains no member, no frame's encoding changes, no `FrameKind` is added, and a result
> payload takes the shape of the method's own declared return annotation (ADR-0085
> §10), so `RecipientGrant` and `PermissionDecision` cross without a second
> declaration and nothing transcribes either into a wire-side schema.

> **Normative.** Peers at different versions do not interoperate, and no lane adds a
> compatibility shim, an optional-member negotiation, a per-member capability flag or
> a lenient decode to make them. ADR-0084 §3's exact-match handshake is the mechanism
> and the refusal naming both versions is the intended user-visible outcome.

### 11. What this ADR does not decide, each with its reason

> **Normative.** Beyond the marked clauses §14 enumerates, this ADR decides nothing.
> It registers no tool, designates no seam, adds no `DestinationProtocol` member, adds
> no `Settings` field, mints no error class, and attests, relaxes or adds no condition
> of ADR-0017 §3 or ADR-0154 §4.

> **Normative.** It decides nothing about `SourceGrant`, `SourceGrants` or
> `SourceGrantStore`. ADR-0097 §7 stands verbatim: a source grant may never be cited
> as `PermissionRuling.authorised_by`, and no `ActionPolicy` may consult either
> source-grant seam.

> **Normative.** It changes no clause of ADR-0193. §1's record, store faces, ceiling
> and digest; §2's construction path, content floor and transcription; §3's five
> comparisons; §4's origin bar; §6's resolution read; §7's check point; §8's partial
> coverage rule; §9's prospectivity, expiry and data rights; and §11's three
> rendering states are all used as given.

Named individually:

- **A durable, filtered or indexed read of the permission trail.** §3 bounds
  `grantable_decisions` by the same number that bounds its window, so a decision that
  has scrolled past it is not offered. ADR-0186 §1's second clause is why no filter
  is minted here — "no filter by tool, by outcome or by window" — and ADR-0231 §19
  already defers "anything §13's record would need a store to answer". **Fires** on a
  measurement showing that real use loses decisions to the window.
- **A user-facing export of the recipient-grant store.** `RecipientGrantStore.export`
  is what discharges ADR-0004 §6 for this store and it reaches no operation here.
  ADR-0186 §9 reserves the bare `assistant export` for ADR-0004 §6's
  whole-installation artifact, and #1502 holds it. **Fires** with that lane.
- **A bounded read over the store's *outstanding* records.** §7 discharges ADR-0193
  §1's recourse with the store's own bounded history, which is what the declared
  surface supplies; what it does not supply is a read answering "which granting
  records still occupy a slot", so a user at the ceiling widens a `limit` rather than
  asking one question. Closing that would mean a member on `RecipientGrantStore`, and
  ADR-0193 §1 rules that *"a contract that adds a member, widens an argument or
  changes a return is changing this decision rather than implementing it"* — so it is
  an ADR partially superseding that clause, not a lane's repair. **Fires** on a
  measurement that a real user reaches the ceiling and cannot find the record.
- **Renewing a grant.** Nothing here extends, re-dates or re-scopes a grant, because
  ADR-0193 §1's store is append-only and its §9 makes changing an authorisation a
  revocation followed by a new grant. A new grant needs a fresh confirmation about a
  real call, so a grant that expires is renewed by the next such call and not by a
  button. **Fires** on an ADR that decides what a renewal would ride, if anything.
- **What a deployment should set `recipient_grant_max_outstanding` to.** ADR-0193
  §13 declines to recommend a value and this ADR declines with it; §6 decides only
  where the ceiling is read and what happens when it refuses.
- **A grant established from a decision whose account has since changed.** Coverage
  compares the `BoundAccount` whole (ADR-0193 §3), so a grant established from an
  older record against an account the user has since reprovisioned covers nothing and
  occupies an outstanding slot until revoked. That is fail-safe, is the same cost
  ADR-0193's Consequences already accept for a declaration edit, and is not repaired
  here. **Fires** on an ADR that decides what a connection act does to standing
  authorisations, which is a question ADR-0193 does not answer either.
- **Whether a browser or a terminal offers an **edit** of the call.** ADR-0233 §13
  leaves the offer to the implementing lanes and §10 fixes the shape of one if it is
  offered; ADR-0193 §2's seventh clause is what governs the act beside it, and §5
  restates that rule and adds nothing.
- **The invocation record and the consume-on-execution step** (ADR-0192, ADR-0016
  §7). §3's `ALLOW` on an abandoned call is not an execution and mints no invocation
  row; nothing here pre-shapes what one would say about it.
- **Detection (#75), a span's origin within the assistant's own store (#1154),
  residency (#95), and the unbounded-read question #1551 asks of the two grant
  stores.** None is touched, and no clause here is cited toward one.

### 12. What the implementing lanes owe

The list below is unmarked and supplies no obligation; the marked clauses in it are
the obligations (ADR-0089 §3).

**Two lanes, in order, and neither before this ADR is `Accepted` and merged** (golden
rule 5, ADR-0015 §5).

**Lane 1 — the contract, the engine and the terminal, in one change.** It lands
`PermissionDecision.from_confirmation`; the five new `AssistantEngine` members of §4 and the
changed signature of `resume`, with their entries in the shared `AssistantEngine` conformance suite and in
`FakeAssistantEngine` (`ai_assistant.testing`); the engine implementation, including
the store's whole face reaching `Engine` from `app/composition.py`; the
`PROTOCOL_VERSION` move of §10 and its commentary entry; and the command-line surface
of §9. No new Protocol is added, so ADR-0137 §3's triad rule has no subject here; what
grows is one existing Protocol, its suite and its canonical fake, which land together
in the same change as they always do.

**Lane 2 — the browser**, with its own ratified decision widening ADR-0177 §1's
enumeration in its own text (§9).

> **Normative.** Lane 1 ships the **opt-in pair** ADR-0193 §2 assigns to the lane
> landing the first establishing surface, on both populations: a user who approves a
> call and asks for nothing standing leaves the answer recorded and the grant store
> **empty**, and a user who asks for it standing leaves **exactly one** grant.

> **Normative.** Lane 1 ships the **ordering pair** ADR-0193 §2 assigns with it,
> asserted over the store's contents and not over what an operation returned: the
> grant is recorded only after `AuditTrail.record` has accepted the answer, and an
> answer the trail refuses leaves the grant store empty.

> **Normative.** Lane 1 ships a test for **each** of §3's seven availability
> conditions, asserting the refusal **by type** rather than that something was
> raised: a `decision_id` the trail does not hold; a decision whose ruling is not a
> `CONFIRM`; one carrying a `step_id`; one carrying an `execution_id`; one the trail
> already holds a resolution for; one whose `expires_at` has passed; one for each of
> `None`, `OriginUnrecordedBinding` and `CoverageUnrecordedBinding` on
> `egress_binding`; and one whose `EgressBinding` carries
> `planned_with_external_content` as `True`. Each asserts that **no** answer and
> **no** grant were recorded, and each asserts that `grantable_decisions` does not
> return the decision either.

> **Normative.** Lane 1 ships the expiry pair, on **both** operations and in each
> case **over a confirmation the policy rules `ALLOW` on**: an expiry at or before the
> instant the answer would carry records neither the answer nor the grant and raises,
> and one strictly after it establishes the grant. The first fails against an
> implementation that let the record's own validator do the refusing, which is the
> outcome §1's clause forbids. Neither arm is stated over a non-`ALLOW` ruling, which
> is the pair below.

> **Normative.** Lane 1 ships the test for §2's binding refusal on the **held**
> population, for **each** of the four shapes it refuses — an `egress_binding` of
> `None`, an `OriginUnrecordedBinding`, a `CoverageUnrecordedBinding`, and an
> `EgressBinding` carrying `planned_with_external_content` — and not for the last
> alone. Each asserts that a `resume` carrying `remember_recipients_until` on such a
> durably parked confirmation seeks no ruling, records no answer, executes nothing,
> raises, and leaves the step `AWAITING_APPROVAL` with its `CONFIRM` unresolved,
> after which the same token answers it without the argument. The `None` arm is the
> one a roster would omit and the one that would otherwise record an `ALLOW` and send
> the call before `established_from` refused a binding that is not there.

> **Normative.** Lane 1 ships the test pinning §3's window-completeness rule: a
> confirmation sharing the oldest returned row's `decided_at` is **not** returned by
> `grantable_decisions` at that `limit`, and is returned at a larger one. It fails
> against an implementation that read the window and filtered on resolution alone,
> which is the implementation that would offer an answered confirmation.

> **Normative.** Lane 1 ships the pair that pins §1's **scoping** of that check, and
> it is the arm a roster would omit: a `resume` carrying an expiry at or before the
> answer's instant beside `approved=False` records the `DENY` exactly as a `resume`
> without the argument does, and an `establish_recipient_grant` carrying one on which
> the policy answers other than `ALLOW` records that answer. Both assert the trail's
> contents, so both fail against an implementation that validated the expiry before
> the policy ruled — the contradiction round 3 of this review found in an earlier
> draft of §1.

> **Normative.** The last of those is owed **by name and not by a roster**, because
> it is the one an implementation reaches through a green path: `ActionPolicy.resolve`
> answers `ALLOW` on such a confirmation when `approved` is true, so an operation
> missing the condition records the answer and only then meets
> `RecipientGrant.established_from`'s refusal. The test fails against exactly that
> implementation and passes against no other.

> **Normative.** Lane 1 ships the pair that separates §2's two non-establishing
> answers: a `resume` carrying `remember_recipients_until` beside `approved=False`
> records the `DENY` exactly as a `resume` without the argument does and establishes
> no grant — asserted over the trail's contents, so it fails against an
> implementation that suppressed the record — and a `resume` carrying it beside
> `approved=True` on which the policy answers `DENY` records that `DENY` and
> establishes no grant.

> **Normative.** Lane 1 ships the test pinning §6's ceiling behaviour: an act whose
> `RecipientGrantStore.record` refuses on the ceiling leaves the answer recorded,
> raises `InvalidRecipientGrantError`, returns no grant, and evicts, narrows,
> expires and truncates nothing. It is arranged over a store already holding the
> configured maximum of **outstanding** records at least one of which is **expired**,
> so it fails against an implementation that counted the live set instead — which is
> the substitution §6 forbids.

> **Normative.** Lane 1 ships the test that pins §7's recourse end to end: a store at
> the ceiling whose slots are held partly by expired grants yields those records from
> `recent_recipient_grants` and none of them from `standing_recipient_grants`,
> `revoke_recipient_grant` on one of them appends a revoking record, and the act
> then succeeds. It is the assertion that ADR-0193 §1's stated recourse is an act the
> user can actually perform.

> **Normative.** Lane 1 ships a test asserting that `from_confirmation` **accepts no
> parameter naming a subject** — by introspecting its signature, as
> `established_from`'s own test does — and one asserting that it refuses a
> confirmation carrying either binding field, so that a later lane cannot route a
> resuming answer through it.

> **Normative.** Lane 1 ships a test asserting that `grantable_decisions` returns
> **no** decision a park holds, arranged over a durably parked step whose `CONFIRM`
> is unresolved, and that the same decision is reachable through
> `pending_confirmations`. It fails against an implementation that filtered on
> `resolves` alone.

> **Normative.** Lane 1 ships **detachment** tests for `grantable_decisions`,
> `standing_recipient_grants` and `recent_recipient_grants`: a caller mutating a
> returned tuple's contents, a returned record through its `__dict__`, or anything
> mutable those reach, changes nothing a later call returns.

> **Normative.** Lane 1 ships a test asserting that no `interfaces/` module imports
> or holds a `RecipientGrantStore`, a `RecipientGrants` or a
> `RecipientGrantResolution`, beside the existing boundary contracts. §4's clause is
> otherwise a rule a reviewer has to notice.

> **Normative.** Lane 1 ships the end-to-end arm this whole decision exists for,
> against a seeded engine and with no network: a recorded egress `CONFIRM` that no
> park holds is offered by `grantable_decisions`, `establish_recipient_grant` records
> an answer and a grant, and a subsequent request over the same tool, account and
> canonical destination set is ruled `ALLOW` on route (b) with `authorised_by` naming
> that grant. It is the test that would have failed on every tree before this one.

### 13. This ADR classified under ADR-0070 §1 and ADR-0082 §1

Unmarked throughout; the classification is a statement about this change, not an
obligation (ADR-0089 §1).

- **ADR-0231 — partially superseded**, §9's second clause, in its second limb alone,
  scoped as the header states. A reader holding only ADR-0231 reads *"no lane … offers
  it to an interface"* as a flat prohibition and would, after this ADR, read it more
  widely than it now holds — which is ADR-0070 §1's test coming out on the
  supersession side, and ADR-0082 §1's test for a record being owed. The clause's
  trailing phrase, *"and §19 defers the surface that would"*, is what makes the
  supersession **partial and narrow** rather than an argument that nothing moved: it
  contemplates the surface arriving and names where it is decided, and §19 names this
  lane. The other two limbs are restated in §3 as this ADR's own obligations rather
  than left to inheritance, so a reader acting on them acts identically before and
  after.

  **The reading under which no record is owed was available and is not taken.** It
  would run: the clause names its own firing condition, so this ADR *satisfies* it
  rather than changing it, exactly as ADR-0193 §15 classified ADR-0148 §3's third
  clause — *"written with its own condition … and this ADR satisfies that condition
  rather than changing the clause"*. The difference is one word. ADR-0148 §3 says
  "**Until** it does, route (a) is the only available route"; ADR-0231 §9 states three
  prohibitions and then says where the surface is deferred, without conditioning the
  prohibitions on that deferral in terms. Where the two readings diverge, the one that
  records is the fail-closed one: a record that turns out not to have been owed is
  removable by showing the test comes out the other way (ADR-0082 §1), and a missing
  one leaves a ratified prohibition reading wider than it holds.

  **The record ADR-0231's header is owed is not made in this change, and that is a
  fence rather than a judgement.** ADR-0082 §7 settles that §1's condition is that the
  superseding ADR **exists**, not that it is ratified, so an atomic pair is available
  to *"a lane whose fence admits both files"* (ADR-0200 §12). This lane's fence admits
  `docs/adr/0235-*.md` alone. The record owed is a second pair on ADR-0231's `Status`
  line — already a leading-token line under ADR-0070 §4's accumulation rule — together
  with the appended dated note ADR-0070 §1 requires, and it is a header-only change
  carrying no decision of its own. **#2090** holds it, filed with this PR, so that a
  reader of either document can find the other.

- **ADR-0177 — neither amended nor superseded, and §9 is what makes that true.** §1's
  enumeration is not widened: none of §4's five new members resolves from a browser
  request, so the figure ADR-0200 §12(a) left at thirty-one is unmoved and every clause
  of §1 reads as it did. `resume`'s new argument is admitted by §1's fourth clause as
  written — an operation is reached "with the arguments the promoted surface declares
  and with no others", and this is one the surface now declares — and it is not the
  deadline class §1's fifth clause closes at three, so that clause is untouched too.
  §1's third clause once counted the promoted operations that are neither in the
  enumeration nor the gateway's own; ADR-0177's own dated note of 2026-08-24 **retires
  that count rather than correcting it**, so four further such operations owe it
  nothing. ADR-0175 §6's third clause likewise needs no record: it writes its own route
  — no lane adds a browser operation without its own ratified decision — and this ADR
  adds none.

- **ADR-0193 — neither amended nor superseded; every clause is used as given.** §13's
  deferral is *satisfied* rather than changed, on exactly the ground ADR-0193 §15 used
  for ADR-0148 §3: it names the surfaces as another lane's to decide and this is that
  decision. §2's clause that *"Which surfaces offer the act, and how they carry it, is
  not decided here"* stays true of ADR-0193. §2's construction-path clause is obeyed —
  every operation here builds its grant with `established_from` — and its refusal list
  is untouched: §3's sixth condition refuses a `CoverageUnrecordedBinding` at the
  **operation**, which is an obligation stacked on a surface ADR-0193 §13 leaves open,
  not a refusal added to the constructor. §1's ceiling clause gains a discharge point
  and no new content.

- **ADR-0178 — no record.** §7's floor is a floor and §5 above stacks an obligation on
  it without making any sentence false; every clause of §7 still holds of every surface
  and §5 relies on them. §11's first clause — *"This ADR decides no `core/protocols.py`
  surface"* — is a statement about ADR-0178's own change and stays true of it; §4 above
  is a different ADR deciding different surface. `Confirmation` gains no member, so
  §10's roster test keeps its count.

- **ADR-0186 — no record.** §1's two operations are unchanged and gain no argument;
  §1's second clause — *"Nothing else is promoted by this ADR"* — is a statement about
  ADR-0186 and stays true. §6's second clause is **used**: it names a later consumer
  lane widening ADR-0177 §1 in its own text as the route, and §9 above takes that route
  by deferring rather than by widening. §7's row floor and §8's bars bind §5's
  population-(b) rendering and are quoted rather than altered.

- **ADR-0233 — no record.** §8's floor binds population (a) whole and §5 reduces
  nothing of it; §11's browser-and-terminal clause is unchanged, and §11's withholding
  clauses are restated in §9 over a wider content class, which adds an obligation and
  makes no sentence of §11 false. §13's *"Whether a standing authorisation may ever
  cover an egress call"* bullet is untouched: ADR-0193 answered that and this ADR
  decides only how the user performs the act ADR-0193 already fixed.

- **ADR-0184 and ADR-0059 — no record.** §3's binding-type and lifetime conditions
  restate refusals those ADRs and `ActionPolicy.resolve` already state, at a surface
  they did not reach; no sentence of either becomes false or over-wide, which is
  ADR-0082 §1's stacked addition.

- **ADR-0097, ADR-0148, ADR-0154, ADR-0181, ADR-0192 and ADR-0226 — no record.** Each
  is cited and none is contradicted. ADR-0097 §7's prohibition is restated in §7 and
  §11; ADR-0148 §3's routes are unchanged and §8's floors are obeyed; ADR-0154 §4's
  attestations are untouched; ADR-0181 §5's floor is inherited through ADR-0193 §4 and
  §6's rendering rule is obeyed in §5; ADR-0192's invocation row is named as not
  minted; ADR-0226 §5's clause binds unchanged and §8 above is what keeps it doing so.

### 14. Marking, review and ratification

Unmarked; a record of route rather than an obligation.

This ADR is marked under ADR-0089: the block-quoted clauses are the whole of what it
obliges. It is contract-surface — §4 adds five members to `AssistantEngine`, one
argument to a fifth, and one classmethod to a `core/types.py` record — so both
required reviews apply under ADR-0015 §1: adversarial and architecture, green on one
tree. It is drafted, reviewed and revised as `Proposed`, and its status is flipped
only once both required reviews have returned clean on one tree, by the one-line
`Proposed` → `Accepted` flip ADR-0165 exempts. `CONTRIBUTING.md` → "Finishing an ADR
PR" is the sequence and it is pointed at rather than re-argued. Nothing implements
against §4 until this has merged (ADR-0015 §5, golden rule 5).

## Consequences

- **The mechanism ADR-0193 built stops being unreachable.** `established_from` gets
  its first caller, `SqliteRecipientGrantStore` gets its first write, and
  `app/composition.py`'s comment about a store that is empty "until a surface offers
  the establishing act" stops describing the system.
- **A search can be serviced, and only after a user has said so.** Milestone 29's
  exit becomes a real search rather than a proven decline — but the route runs through
  a refused search the user is shown, a recipient set they authorise, and an instant
  they choose. Nothing about ADR-0231 §9's chain is weakened: the declaration still
  discloses, the disclosure floor still fires, and route (b) is still the only way to
  an `ALLOW`.
- **A recorded `ALLOW` that authorises nothing runnable becomes an ordinary row.**
  §3's answer is the first decision in this corpus recorded about a call the system
  has already abandoned. §5's disclosure clause is what keeps a user from reading it
  as a promise, and ADR-0192's invocation row is what will one day say whether
  anything ran.
- **The trail becomes a thing a user acts on, not only reads.** `recent_decisions`
  made history legible; `grantable_decisions` makes one row of it actionable. §3's
  outstanding-work clause is the whole of what stops that becoming an inbox, and it
  is stated at the surface because nothing mechanical distinguishes a listing from a
  queue.
- **Two grant vocabularies is a cost paid deliberately.** A user now learns two sets
  of commands for two kinds of permission, and a page that shows both has to keep them
  visibly apart. The alternative — one noun over two records that cannot substitute
  for each other — is how someone comes to believe that revoking a source grant
  stopped a send.
- **The ceiling becomes visible where it bites, and only there.** §6 leaves it
  exactly where ADR-0193 §1 put it — inside `record`, atomic, over the outstanding
  set — and adds the obligation that its refusal reach the user with the ceiling
  named and a recourse beside it. What §7 adds is the listing that makes the recourse
  performable, which is a read the corpus had built and never promoted.
- **A voice-only deployment cannot establish a grant at all.** Every send stays a
  confirmation on a screen, and a user with no screen is where ADR-0207 already left
  them. That is disclosed here rather than discovered.
- **The browser gains a wire it does not yet use.** `resume`'s new argument crosses
  to a browser that has no control for it until Lane 2, and the five new operations do
  not cross at all. A user of the page sees no change from this ADR, which is the
  sequencing §9 chose and not an oversight.

## Alternatives considered

- **One operation covering both populations, taking a decision id.** Rejected: for a
  park the answer must go through `resume`, which rebinds and executes, and an
  operation that answered a park from a trail row would either author a second answer
  to a settled binding or duplicate `resume`'s whole path badly.
- **A follow-up call establishing the grant from an already-recorded answer.**
  Rejected: it is not "in the same act" (ADR-0193 §2), it loses the standing request
  to any client that stops between the two calls, and it would let a grant be
  established from an answer given months ago without the call being shown again —
  out-of-call establishment through the back door.
- **A "remember this provider" surface that composes a probe call to get a
  confirmation to answer.** Rejected by name in §3: ADR-0193 §2's second clause
  forbids out-of-call establishment and its commentary forbids a surface rendering a
  fabricated call-level fact.
- **Making the `WEB_SEARCH` `CONFIRM` a real park so `resume` reaches it.** Rejected:
  it is exactly what ADR-0231 §9's first limb forbids and what that ADR's own
  Alternatives refused twice, and it would put a durable confirmation and a resume
  path behind a read mechanism designed to be invisible.
- **Widening `established_from` to refuse a `CoverageUnrecordedBinding`.** Rejected in
  favour of refusing at the operation: the constructor's refusal list is a marked
  clause of ADR-0193 §2, and the condition is a precondition on a surface ADR-0193 §13
  left open rather than a change to what the constructor does.
- **Widening ADR-0177 §1's enumeration now, so the browser lands with the terminal.**
  Rejected on ADR-0186 §6's precedent and its reason: the card is under active change
  for ADR-0233 §8, the exit is measurable on the terminal, and the enumeration should
  be widened by the lane that has a surface argument for each operation it admits.
- **Promoting `standing` alone and leaving the store's history unpromoted.**
  Rejected on review: the ceiling counts outstanding records and an expired one is
  outstanding but not live, so a user at the ceiling would hold a record that appears
  in no listing and have no id to revoke — ADR-0193 §1's stated recourse naming an act
  they cannot perform. §7 promotes `recent` for exactly that, and only that.
- **Promoting `RecipientGrantStore.export` beside them.** Rejected: it is the
  unbounded read ADR-0193 §1 declines to bound, and ADR-0186 §9 reserves the bare
  `assistant export` for ADR-0004 §6's whole-installation artifact, which #1502 holds.
- **A mandatory pre-write count of outstanding grants, so the act fails before the
  answer is recorded.** Rejected on review, because the declared store surface
  supplies no such count: `standing()` is live-only and undercounts, `recent(limit)`
  is bounded and mixes in revocations, and `export()` is the unbounded read. The
  choices were to widen ADR-0193 §1's exact surface or to make every act read a Tier 1
  store whole, for a check `record` would have to repeat anyway — so §6 puts the
  ceiling where ADR-0193 §1 already put it and rules what the surface must say.
- **A `Settings` default lifetime for a grant, so a surface could offer one.**
  Rejected in §1: ADR-0193 §9 puts the instant in the user's act, and a configured
  default is the grant-minted-from-configuration shape ADR-0097 §8 refuses.
