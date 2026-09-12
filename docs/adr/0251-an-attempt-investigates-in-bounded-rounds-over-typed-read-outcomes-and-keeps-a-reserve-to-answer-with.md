# 251. An attempt investigates in bounded rounds over typed read outcomes, and keeps a reserve to answer with

- Status: Proposed
- **Partially supersedes four ADRs, in seven narrowly stated scopes** — three of
  [ADR-0228](0228-a-serviced-read-may-revise-the-plan-once-and-the-turn-stops-looking-at-a-bound-or-a-deadline.md),
  two of
  [ADR-0240](0240-the-planner-asks-by-window-and-label-and-an-empty-structured-read-sends-it-back-to-plan.md)
  one of
  [ADR-0247](0247-the-configured-web-search-provider-is-the-destination-the-owner-chose-and-the-recipient-they-granted-and-the-call-budget-is-removed.md)
  and one of
  [ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md)
  — and §15 shows the working for every one.
  **ADR-0228's three:** §2's **condition (e)**, together with the enumeration's
  completeness (its "if and only if **all** of the following hold" read as a claim that
  the list is closed), as ADR-0240 §6 left both — (e) is dissolved and three further
  conditions are added, while §2's all-of-them rule, its mechanical-not-a-judgement rule,
  its closing clause, its prohibition on an implementation retrying, widening or
  substituting a read, and conditions (a), (b), (c), (d) and (g) all bind **verbatim**.
  §3's **count and its subject**, *"A turn makes **at most two** calls to
  `Planner.plan`"* — a per-turn **total** becomes a per-**attempt admission threshold on
  iteration**: a further call within a turn is admitted only while the attempt's consumed
  calls are fewer than its kind's declared allowance, every turn the owner starts makes its
  first call whatever the ledger holds, and the attempt's total is therefore bounded by how
  many times the owner asks rather than by a figure. §3's **non-configurability** binds
  entire and is the clause this decision is built on, its servicing-the-last-request rule
  binds entire, and its stopped-at-the-bound rule binds entire over the new figure. And §9's
  **five-member closure** of the stop vocabulary, in that **count alone** — the count
  becomes seven; every existing member keeps its name, its value and its meaning, and
  §9's one-record rule, its counts-and-no-copy rule, its per-turn fire rate and its
  stop-distribution clause bind entire and are extended.
  **ADR-0240's two:** §7's **parameter declaration**, *"`Planner.plan` gains one keyword
  parameter, `empty_reads: Sequence[ReadAsk] = ()`"* — the parameter becomes
  `read_outcomes: Sequence[ReadOutcome] = ()`, which carries the same asks and says more
  about each; every other clause of §7 — the ask carried back byte for byte and never
  edited, that nothing the store said crosses on it, that a read the budget did not reach
  is not in it, the separate-governance clause and the breaking-change clause — binds
  **verbatim** and is restated over the wider carrier. And §6's **narrowing to
  `STRUCTURED_READ`**, in the respect that an empty read of **any** kind now reaches the
  planner as a typed outcome; §6's definition of an empty structured read, its rule that
  a deduplicated-out read is not one, its **broadening-is-the-planner's** clause and its
  prohibition on citing ADR-0237 §7 as its ground all bind entire.
  **ADR-0247's one:** §5's **per-turn sentence**, *"**Per turn**: ADR-0228 §4's planning
  budget gates the start of each additional planner call, so a turn that declares one
  starts at most two planner calls and therefore at most two searches"* — the figure two
  stops being true of a turn inside an attempt that declares a larger allowance. §5's
  per-search, per-money and **per-conversation** clauses bind **verbatim**, and §11 is
  §13's first deferral answered in the direction §5 points.
  **ADR-0249's one:** §7's **`Planner.plan` parameter-preservation clause**, in the
  `empty_reads` term alone — *"keeps `context`, `memories`, `capabilities`, `files` and
  `empty_reads` **exactly as they stand**"* — which stops being true once that parameter becomes
  `read_outcomes`. The four other named parameters are kept exactly as they stand, and every
  remaining clause of §7 binds entire: the `GoalBrief` first parameter, the `utterance` and
  `evidence` keywords, the `PlannerOutput` return, the annotation clause, the
  keyword-parameters-not-a-bundle ruling, the `PlannerOutput` field enumeration and its
  `None`-is-not-an-error clause. §§1-6 and §§8-17 are untouched.
- **No other ADR is superseded in whole or in part**, and §15 shows the working for each
  one a reader would expect to be — ADR-0226, ADR-0250, ADR-0194, ADR-0241 and
  ADR-0237 among them. **ADR-0226 is untouched**, which is the one a reader should check
  first: a fourth round reaches a fourth citation level by exactly the mechanism ADR-0228 §8
  already ruled and by no other.
- **Decides a change to `src/ai_assistant/core/types.py` and to
  `src/ai_assistant/core/protocols.py`** — two new types, one new enumeration, one further
  member on `AttemptEffort`, and one parameter replaced on `Planner.plan`. **It is a
  BREAKING contract change under golden rule 5** and is ratified and merged as its own PR
  before anything implements against it (ADR-0015).
- Date: 2026-09-12

## Context

### Where this comes from

Milestone 32's L3 (#2169) and L4 (#2170), adopted from the owner's ruling on #1908 of
2026-09-09. #1908's M32 paragraph states both in one sentence: *"Ratify a bounded
repeated read/decide loop, its distinct operation outcomes and an explicit amendment to
ADR-0228's two-call bound where needed. Demonstrate an investigation that requires more
than two decision rounds and chooses a later operation from newly discovered evidence;
distinguish empty, duplicate, refused, failed and truncated reads. Demonstrate
sufficient-context restraint, useful continuation, unproductive repetition stopping, and a
useful partial answer at exhaustion. Decide allowance representation and preserve capacity
for composition and verification."*

It is **A3** of the delivery breakdown the owner approved on #2255 on 2026-09-12, and
three of that ruling's clauses bind it directly: the standing rule that convenience alone
never justifies a user-facing restriction; **decision 8**, that a useful real-information
reader lands alongside M32, which fixes what this loop may assume about its sources and
no more; and two of the three corrections — **correction 1**, that *"Refreshed evidence
needs supersession rules, so retained historical disagreements do not permanently block
progress"*, and **correction 3**, that *"When understanding changes during investigation,
subsequent planning receives the updated goal view and identifies the interpretation
revision it targets."*

[ADR-0249](0249-the-goal-carries-its-interpretation-the-attempt-carries-the-phase-and-the-planner-returns-its-understanding.md)
§13 defers to this decision by name — *"The bounded investigation loop, the per-attempt
allowance, its reserve, progress and stopping, and any further member of
`AttemptEffort`"* — and §4 assigns it one more: *"`ABANDONED` and `BLOCKED` likewise gain
no producer here; which act writes each is A2's and A3's respectively"*.
[ADR-0250](0250-a-turn-finds-its-goal-before-it-plans-and-a-material-ambiguity-becomes-one-durable-question-bound-to-that-goal.md)
§12 took A2's half and left the rest here in terms: *"**A3 may name further acts for the
investigation loop and may name none that is not a user act**"*.

And
[ADR-0247](0247-the-configured-web-search-provider-is-the-destination-the-owner-chose-and-the-recipient-they-granted-and-the-call-budget-is-removed.md)
§13's first deferral is fired by this decision and answered in §11. Its trigger is the
owner's own, quoted there: *"Revisit if planner passes, batching or unattended work
expand."* Planner passes expand here, so the trigger fires and this ADR owes the answer.

### What the tree does today, read rather than assumed, at `origin/main` `5c3bdd52`

- `orchestration/loop.py` declares `_PLANNER_CALL_BOUND: Final = 2` and
  `_PLANNING_BUDGET: Final = timedelta(seconds=20)`, and `_PLANNING_BUDGETS` maps
  `ConversationalOperation.CONVERSE` and `CONVERSE_STREAMING` to that figure.
  `CONVERSE_SPOKEN` is **absent**, and the module's own comment says why: *"converse_spoken
  is absent deliberately and is the one member whose absence is itself a decision … every
  future member is absent by accident until someone prices it, and gets the same answer."*
- `ConversationalOperation.planning_budget` is `_PLANNING_BUDGETS.get(self)` — a lookup
  with a `None` default and never a branch with a figure at the end of it.
- `orchestration/reads.py` declares `StopReason` with **five** members — `NOT_ITERATED`,
  `SETTLED`, `BOUND_REACHED`, `BUDGET_REACHED`, `PLANNING_FAILED` — and it lives in
  `orchestration` rather than in `core` because it crosses no subsystem boundary.
- The read vocabularies the servicing produces are `SearchDisposition` (seventeen members,
  `orchestration`), `StructuredOutcome` (five, `orchestration`), `SearchRefusal` (seven,
  `core`), `FetchRefusal` (five, `core`) and `MemorySearchResult.capped` (a bool,
  ADR-0128 §2). None of them reaches a planner.
- `Planner.plan` carries `empty_reads: Sequence[ReadAsk] = ()` (ADR-0240 §7), rendered by
  `planning/planner.py::_render_empty_reads`. `loop.py` accumulates it as
  `empty_reads += () if carried.empty_read is None else (carried.empty_read,)`, so at most
  one ask per servicing and only a `STRUCTURED_READ` one.
- `loop.py` computes `stopped_while_asking=(audit.stop in {StopReason.BOUND_REACHED,
  StopReason.BUDGET_REACHED})` and hands the bare boolean to `composing.py`, which takes it
  as a keyword at three sites. ADR-0228 §10's carrier exists and works.
- **ADR-0249's L1 has landed and every shape this decision builds on is read from the tree.**
  `core/types.py` declares `AttemptEffort`, frozen and `extra="forbid"`, with **exactly**
  `planner_calls: int` (`default=0`, `ge=0`) and `working: timedelta` (`default=timedelta(0)`,
  `ge=timedelta(0)`), and its docstring carries the licence this decision exercises: *"**A3
  fixes the allowances, the reserve and any further member** (§13)."* `GoalAttempt` carries
  exactly the twelve fields ADR-0249 §5 enumerates, with `effort` defaulting to a fresh
  `AttemptEffort` and a `_terminal_states_carry_their_result` validator over
  `TERMINAL_ATTEMPT_STATES`. `AttemptPhase` holds six members in ADR-0249 §6's order,
  `AttemptState` seven, `AttemptOutcome` six, `GoalStatus` four, `EvidenceStanding` three; and
  `GoalBrief`, `BriefElement`, `PlannerOutput`, `ProposedUnderstanding`, `EvidenceDigest`,
  `GoalRevision` and `AttemptTransition` are all present, with `PlanStore` carrying
  `open_attempt`, `get_attempt`, `attempts_of` and `commit_attempt`. `PROTOCOL_VERSION` is
  **38** and `PlanExport.schema_version` is **8**.
- **`AttemptKind` and `ReadOutcomeKind` are absent**, which is what this decision mints; and
  **`PlanStore.set_goal_status` is absent**, because ADR-0250's implementation has not landed.
  §9 names it as `BLOCKED`'s write path on ADR-0250 §9's ratified text, which is the ordinary
  state under ADR-0015 — a contract is ratified before anything implements it — and this ADR
  says so where it does it.

### The four ADR-0249 clauses this decision is built on

Quoted once here and relied on throughout. The **shapes** they describe are in the tree above;
what is quoted is the **rule**, which is the ADR's and not the code's.

§5: *"`AttemptEffort` is a frozen model with `extra="forbid"` carrying at least
`planner_calls`, an `int` `ge=0`, and `working`, a `timedelta` `ge=0` accumulating the
attempt's **working** intervals and **excluding every interval spent waiting for the
user**. Both are monotonically non-decreasing within an attempt: **no replan, branch,
recovery or phase transition resets either**, and no implementation subtracts from one."*
And: *"**A3 fixes the allowances, the reserve and any further member of `AttemptEffort`**
(§13)."*

§5 again: *"**A reopened goal starts a new attempt**, and an attempt is opened only by a
**user act**. No implementation opens an attempt in order to obtain a fresh allowance, and
no replan, branch or recovery opens one."*

§6: *"Within one attempt, `phase` **advances in that order and never moves backwards**…
**Recording an interpretation revision does not move the phase**: an understanding revised
during investigation advances the goal's `version`, which is what §8's stale-target rule
keys on, and leaves the attempt where it stood."*

§4: *"`GoalStatus`'s four members are the goal's **overall disposition**… They are **not**
the state of any one attempt: an attempt may be blocked while the goal is `ACTIVE`, and
`BLOCKED` on the goal means *this objective cannot currently be achieved*."*

### The gap this closes, stated as the two failures the tree has today

**A turn cannot follow a fact it discovered.** ADR-0228 §3 bounds a turn at two planner
calls, so the first plan asks, the second plan sees the answer, and there is no third plan
to act on what the second one learned. #2169's acceptance scenario — *"A later
investigation step depends on a fact discovered after the initial search and fetch"* — is
not reachable, and #1908 says so in terms: *"The test requires more decision rounds than
the current two-call bound permits."*

**The planner is told almost nothing about why a read produced nothing.** Seventeen
`SearchDisposition` members, seven `SearchRefusal` members, five `FetchRefusal` members and
a `capped` boolean all collapse, at the planning seam, into the absence of a record.
ADR-0240 §7 opened the seam for exactly one case — an empty structured read — and its own
argument generalises: *"Without §7 this section would be exactly what (e) forbids"*, because
what makes a second call worth its round trip is having an input the first call did not
have. A refused source and an empty one are different facts, and a planner that cannot tell
them apart cannot do what #2169 asks — *"An inaccessible source produces a justified
alternative or an honest stop."*

### What this ADR is not allowed to settle

It decides the **loop, the allowance, the stop and `BLOCKED`**, and nothing about what a
read reaches. It mints no `ReadKind`, widens no ask, adds no source, decides nothing about
evidence rows or their supersession (A4's), nothing about authorization (A6's), nothing
about driving a plan (A7's and A9's), nothing about verification or which `AttemptOutcome`
an attempt earns (A10's), and nothing about the real-information reader decision 8 places
alongside M32 — it names what the loop needs from such a reader (§14) and designs none of
it. It decides no figure that lives in `Settings`, and it reintroduces no per-conversation
bound of any kind (§11).

## Decision

### 1. The round, and where the rounds sit

> **Normative.** A **round** is one `Planner.plan` call together with the servicing of the
> `read_request` that call returned, where it returned one. An attempt's investigation is a
> sequence of rounds, each call choosing its read from the **typed outcomes** of the reads
> this turn has already made (§3). **A round is one planner call, so the attempt's
> planner-call allowance (§5) is a count of rounds.**

> **Normative.** **Every round of one attempt's investigation sits inside one occupancy of
> `AttemptPhase.INVESTIGATE`.** No round moves the phase, forward or backward. ADR-0249 §6's
> rule that the phase *"advances in that order and never moves backwards"* binds **verbatim**,
> and so does its clause that *"Recording an interpretation revision does not move the
> phase"*: a round that returns an understanding the loop records advances the **goal's**
> `version` and leaves the attempt where it stood. There is no re-entry into `INVESTIGATE`
> from a later phase, and no clause of this decision creates one.

> **Normative.** **The turn is still assembled once.** ADR-0228 §1's clauses bind verbatim
> over N rounds as they bind over two: the context is assembled once per turn and every round
> of that turn receives the same `CurrentContext`; the conversation tail, the retrieval and
> the episodic supplement are read exactly once per turn; the capability vocabulary is read
> again immediately before **each** planner call (ADR-0211 §3); and a plan's decision content
> is authored at the `Planner.plan` seam and nowhere else. What a round plans over that the
> round before it did not is the fourth group and the carrier of §3, and nothing else.

> **Normative.** **The supply stays monotone across a turn's rounds, and monotonicity is not
> claimed across an attempt's turns.** ADR-0228 §7 binds **entire and at its own scope**: the
> three groups keep their contents, their order and their positions; the fourth group only
> grows; nothing is removed between a turn's first planner call and its last; and no
> implementation subtracts, re-filters, re-ranks or re-orders the supply on account of a round.
> §7's one-fourth-group rule, its per-servicing budget of ten, its whole-union deduplication,
> its once-after-the-last-servicing evaluation and its construct-the-`TurnResult`-once rule all
> bind over a turn's rounds however many there are, unchanged.

> **Normative.** **A later turn of the same attempt assembles its own supply and inherits
> none.** ADR-0228 §1 assembles the supply once **per turn** and ADR-0052 §3 leaves it
> unpersisted — *"context and retrieved memories are ephemeral and were never persisted"* — so
> a later turn's three groups are read afresh and may differ, and a process restart between two
> turns of one attempt reconstructs nothing. **No clause of this decision requires an attempt's
> supply to survive a turn, and no lane builds one that does.** What survives a turn boundary
> is the ledger (§5) and the goal's interpretation (ADR-0249 §1), both of which are durable
> because those decisions made them so.

> **Normative.** **Each round's call receives the `GoalBrief` of the goal's interpretation as
> it stands at the moment of that call**, and the plan it returns carries the
> `targets_revision` the loop stamps (ADR-0249 §8). Where round *k* returned an understanding
> the loop recorded, round *k+1*'s brief is the **new** revision's. This is the owner's
> correction 3 as a mechanism, and ADR-0249's own record against ADR-0228 §1 states it for two
> calls in the words this section generalises to N: *"a second call planning against an
> understanding the first call superseded is exactly what correction 3 forbids."*

**One `INVESTIGATE` occupancy rather than a phase that oscillates, because the alternative
costs the phase its meaning.** ADR-0249 §6 buys six phases as *"six responsibilities and six
observable transitions"*, and a phase a loop could re-enter would make "which phase is this
attempt in" a question whose answer depends on how many times you asked. The rounds are
**inside** `INVESTIGATE` for the same reason the revision is inside a turn today: what
iterates is the enquiry, not the lifecycle.

**A turn's second assembly is refused here for ADR-0228 §1's own reason, and the reason gets
stronger with more rounds, not weaker.** *"Re-running them would return the same records for
the same query and would put a second `MemoryStore` read on the turn path for nothing."* Four
rounds would put three such reads on it.

### 2. `ReadOutcomeKind`: seven members, and every source vocabulary maps onto exactly one

> **Normative.** `core/types.py` gains **`ReadOutcomeKind`**, a `StrEnum` valued by
> lower-cased member name and **closed at exactly seven members**: `RETURNED_RECORDS`,
> `EMPTY`, `DUPLICATE`, `TRUNCATED`, `REFUSED`, `FAILED` and `EXPIRED`. The vocabulary is
> **added to and never renamed**, and no implementation, setting or later lane adds an eighth
> without the ADR that decides it — ADR-0221 §5's pattern, for its own reason.

> **Normative.** Each member states **what became of one ask**, and the seven are disjoint and
> exhaustive over the asks a servicing reached:
>
> - **`RETURNED_RECORDS`** — the servicing completed and added **at least one record the
>   supply did not already hold**, counted after ADR-0226 §7's deduplication.
> - **`EMPTY`** — the servicing completed and the source returned **no record at all**. An
>   empty structured read in ADR-0240 §6's sense is this member; so is a `WEB_SEARCH` whose
>   provider answered with nothing (`SearchRefusal.NO_RESULT`), and so is a `SIGHTED_QUERY`
>   the store matched nothing for.
> - **`DUPLICATE`** — the servicing completed and returned records, and **every one of them
>   was already in the supply**. This is precisely the shape ADR-0228 §2(e) calls *"a servicing
>   whose every record was deduplicated out"*, and ADR-0240 §6's clause that such a read is
>   **not** empty binds verbatim: *"the store returned records, and a planner told otherwise
>   would broaden away from records already in front of it."*
> - **`TRUNCATED`** — the source answered and **did not certify that the answer was
>   complete**: ADR-0226 §6's budget of ten cut a kind's yield, or `MemorySearchResult.capped`
>   was `True` (ADR-0128 §2), or a structured read's own window ceiling bound it. **It says
>   that completeness was not certified and never that more records exist.** ADR-0128 §2 is
>   explicit about its own half of that — `True` on a short result *"is a refusal to certify
>   and never a claim that more exists"*, and an implementation *"reports `True` … where a
>   read's eligible set exactly meets its ceiling"* — so a member asserting more existed would
>   be a false statement the planner could act on. Records may or may not have reached the
>   supply, and whether the round was **productive** is decided by whether any did (§7) and
>   never by this member.
> - **`REFUSED`** — the source **decided** not to answer, on a ground it owns. Every ruling,
>   spend, composition, configuration and attestation member of `SearchDisposition`, every
>   such member of `SearchRefusal` (`SPEND_REFUSED`, `PROVIDER_REFUSED`, `UNATTESTED`),
>   `FetchRefusal.NOT_FOUND`, `NOT_A_FILE` and `TOO_LARGE`. **A servicing `Servicing.DECLINED`
>   under ADR-0226 §5's channel scoping is not this member and is not any member**: it is case 1
>   of the classifier below, which produces no entry at all, because nothing about one ask was
>   decided — the whole request was never put.
> - **`FAILED`** — the servicing **completed and the source's answer was a failure**:
>   `SearchRefusal.TRANSPORT_FAILED` and `RESPONSE_TOO_LARGE`,
>   `SearchDisposition.SEARCH_FAILED`, `TRANSPORT_FAILED` and `BINDING_FAILED`,
>   `FetchRefusal.UNREADABLE` and `EXTRACTION_FAILED`. **A source failure is not a servicing
>   failure**, and the two are kept apart deliberately: ADR-0231 §17 rules that *"Every member
>   is returned and none is raised"*, so a transport that fell over is a completed servicing
>   carrying a typed non-yield, and ADR-0228 §2(d)'s *"servicing that failed or was partial"*
>   is the loop's own stage not running to its end. The first is this member and admits a
>   further round; the second yields **no outcome entry at all** and fails (d).
> - **`EXPIRED`** — a **deadline** passed: `SearchRefusal.DEADLINE_EXPIRED` and
>   `SearchDisposition.DEADLINE_EXPIRED`.

> **Normative — the classifier, and it is not an enum-to-enum table.** One ask's outcome is
> **classified from the servicing's own per-ask facts, in one place**, because no source
> enumeration determines the answer on its own: `StructuredOutcome.RETURNED_RECORDS` describes
> both a read that added records and one whose every record deduplicated out, and a
> `MemorySearchResult` can be `capped` while still admitting records. The facts are exactly
> four: **whether the servicing's stage ran to its end**; **the source's typed non-yield, where
> it produced one** (`SearchDisposition`, `SearchRefusal`, `FetchRefusal`, `StructuredOutcome`);
> **how many records the ask admitted after ADR-0226 §7's deduplication, and how many it
> returned before it**; and **whether completeness was certified** (ADR-0226 §6's cut,
> `MemorySearchResult.capped`, a window ceiling).

> **Normative — the precedence, and it is total.** The classifier is one function over those
> four facts, evaluated in this order, with **no default branch and no fallback member**:
>
> 1. **No entry at all** — the ask was not made, the budget did not reach it, or the
>    servicing's stage did not run to its end. `StructuredOutcome.NOT_ASKED`,
>    `StructuredOutcome.NO_SLOT`, `SearchDisposition.NO_BUDGET` and a declined or partial
>    servicing under ADR-0226 §5 are each in this case. ADR-0240 §7's clause binds verbatim:
>    *"A read the budget did not reach is not in it."*
> 2. **`EXPIRED`**, where the non-yield is a deadline member.
> 3. **`FAILED`**, where the non-yield is a failure member.
> 4. **`REFUSED`**, where the non-yield is a decision member.
> 5. **`EMPTY`**, where the source returned **no record at all** before deduplication.
> 6. **`DUPLICATE`**, where it returned records and admitted none after deduplication.
> 7. **`RETURNED_RECORDS`**, where it admitted at least one.
> 8. **`TRUNCATED`** displaces 5, 6 and 7 — and only those — where completeness was not
>    certified. A cut, capped or ceiling-bound answer is `TRUNCATED` whether it admitted
>    records, admitted only duplicates, or admitted none.
>
> **`Servicing` is not one of the classifier's inputs**, because it is the stage's disposition
> for the whole request rather than an answer about one ask: `Servicing.DECLINED` lands in case
> 1 and `Servicing.SERVICED` says nothing about any individual ask.

> **Normative.** **Exactly one entry per ask the servicing reached**, and every ask the
> servicing reached has one. The implementing lane pins the classifier by **enumerating the
> combinations of the four facts** — including the exact-ceiling `capped` case, a capped read
> admitting records, a capped read admitting none, and a fully-deduplicated read — and not by
> enumerating enum membership, which is the shape this clause replaces.

> **Normative.** **No member carries a message, a ground, a provider name, a query, a
> destination, a monetary figure, a duration, a count or a `Settings` field name**, and no
> statement rendered for one carries any of them. ADR-0242 §9's bar binds this vocabulary as
> it binds `SearchNotServiced`, and for the same reason: **it states what became of the ask
> and never why a source ruled the way it did.**

> **Normative.** **`EXPIRED` is its own member and is not folded into `FAILED`.** ADR-0241 §4
> made an expiry *an outcome of its own* rather than a failure, and this vocabulary keeps that
> distinction at the seam where it can be acted on: a deadline that passed says the source may
> well answer if asked with more room, where a transport that failed says nothing of the kind.

**Seven members rather than the obligation's five, and both additions are named by the
corpus rather than invented.** #2169 asks for *"success, empty results, duplicates, refusal,
failure, and truncation"* — six. `EXPIRED` is the seventh because ADR-0241 §4 already ruled
that an expiry is not a failure, and collapsing them here would undo a ratified distinction
one seam over.

**`REFUSED` and `FAILED` are separated because they license different next moves and #2169
says so.** *"An inaccessible source produces a justified alternative or an honest stop."* A
refusal is a decision that will be taken again — the same ask to the same source gets the
same answer — so the justified alternative is a **different source**. A failure is a
transient the same ask may survive. Neither **authorises** a retry (§4), and the difference
is what makes the planner's next choice informed rather than a guess.

**Why this enumeration is in `core` when `StopReason` is not.** ADR-0231 §13's test decides
it, and it comes out the other way here: `StopReason` *"crosses no subsystem boundary, being
the servicer's own account"*, where `ReadOutcomeKind` is carried across the `Planner.plan`
seam into `planning` and is therefore public data between subsystems, which golden rule 1 and
`CLAUDE.md`'s conventions put in `core/types.py`.

### 3. `ReadOutcome`, and `empty_reads` becomes `read_outcomes`

> **Normative.** `core/types.py` gains **`ReadOutcome`**, a frozen model with
> `extra="forbid"` carrying exactly two fields: **`ask`**, a `ReadAsk` — the frozen ask the
> planner itself emitted, carried back byte for byte — and **`outcome`**, a
> `ReadOutcomeKind`. It carries nothing else.

> **Normative.** `core/protocols.py`'s `Planner.plan` **replaces** its `empty_reads:
> Sequence[ReadAsk] = ()` parameter with **`read_outcomes: Sequence[ReadOutcome] = ()`**,
> additive in shape and defaulted, in the same keyword position. Every other parameter, the
> return type and every other Protocol are unchanged by this clause. **This is a BREAKING
> contract change under golden rule 5** and is flagged as one; an implementation that accepts
> the parameter and ignores its value means exactly what it meant, and ADR-0230 §3's paragraph
> on its own `files` is inherited whole and not re-argued.

> **Normative.** It carries **one entry per ask this *turn* has already serviced, in servicing
> order**, and nothing else. On a turn's **first** planner call it is always `()`, and `()`
> means **no read of this turn has been serviced** — which is the semantically correct answer
> for the first call, for a turn that asked for nothing, for a servicing that was declined or
> that the budget did not reach, and for a `Planner` that knows nothing of this parameter.
> ADR-0240 §7's own scope is kept exactly.

> **Normative.** **Nothing the source said crosses on it.** ADR-0240 §7's clause binds
> verbatim over the wider carrier: *"No record, no count, no identifier, no instant of the
> read, no `capped` value and no value of any kind that the store returned or computed."* The
> only content it carries is the planner's own prior composition and one member of a closed
> vocabulary.

> **Normative.** **The ask is carried back unaltered and is never edited on the way.** ADR-0240
> §7 again, verbatim: *"No implementation widens a window, drops an axis, rewrites a label or
> composes a suggested ask to put in its place."* What a later round receives is what an
> earlier round emitted, and the ask the later round makes is its own composition.

> **Normative.** **This carrier and the audit are governed separately**, and neither is read
> as licence for the other (ADR-0240 §7). The audit is a Tier 2 log event bound by ADR-0226
> §9's counts-and-no-copy rule; this carrier is an in-process argument handed to the author of
> the value it carries.

> **Normative.** **The carrier does not span the attempt, and it mints nothing durable.** No
> `PlanStore` member, no `core` field and no store column is added for it; it is an in-process
> argument built from the turn's own servicings and discarded with the turn. **What spans the
> attempt is the ledger** (§5), which is durable because ADR-0249 §5 made it so.

> **Normative.** **The planner is still not told which round it is on.** ADR-0228 §12's clause
> binds in the half ADR-0240 §7 left standing: *"**the planner is not told which iteration it
> is on**. No lane adds an iteration index, a 'last look' instruction or any other signal to
> the planner's input."* No round index, no count of rounds made or remaining, no allowance, no
> reserve, no elapsed figure, no attempt kind and no stop reason reaches a planner's input, on
> this carrier or on any other. What crosses is **what each ask returned**, which is a fact
> about the world and not a fact about the loop's budget.

**The carrier stays scoped to the turn, and the reason is that an outcome has no durable home
and this decision declines to mint one.** An attempt may span several turns (ADR-0250 §12: a
turn associating to a goal whose attempt is non-terminal opens none), and an attempt told on
turn 1 that a source refuses would in principle be better off remembering it on turn 3. But a
`ReadAsk` is recoverable from the attempt's persisted plans (ADR-0249 §5's `plan_ids`,
ADR-0228 §5's persistence) and a **typed outcome is not recoverable from anything**: the supply
it was computed over is ephemeral by ADR-0052 §3. Carrying it across turns therefore means a
`PlanStore` widening, and ADR-0249 §10 has already booked one for A4's evidence rows — two
widenings of one store inside one milestone, for two overlapping records of what a read
returned, is the collision that decision warns about. **§14 defers the cross-turn carrier with
what fires it**, and what does not wait for it is the part that actually bounds the loop: the
counters are the attempt's, durable, and unreset by a turn boundary.

**Replacing `empty_reads` rather than adding a second parameter beside it, because two
carriers for one fact is the defect neither would show on its own.** ADR-0240 §7's parameter
carries exactly the asks that came back empty; `read_outcomes` carries those same asks with
`outcome` `EMPTY`, and every other ask besides. Keeping both would put one ask in two places
with two spellings of its state, and the first implementation to disagree with itself would
be right in one of them. ADR-0249 §9 makes the same call for the open questions — *"One
carrier is kept, it is the brief"* — and for the same reason.

**And the generalisation is ADR-0240 §7's own argument taken at face value.** §6 says of
itself: *"the amendment is not a claim that the second call is worth making anyway: it is
paired with §7, which gives the second call an input the first did not have. **Without §7
this section would be exactly what (e) forbids**."* §4 below dissolves (e) for every outcome
rather than for one, so it owes the same pairing for every outcome — which is this section.
ADR-0240 §6's narrowing to `STRUCTURED_READ` was correct **for its own question**, which was
whether an otherwise-inadmissible round should fire; it is not a claim that a planner should
be kept ignorant of a refusal on a round that fires anyway.

### 4. What admits a further round: ADR-0228 §2, with (e) dissolved and three conditions added

> **Normative.** The loop makes a **further planner call** within an attempt if and only if
> **all** of the following hold. Each is a fact the loop already has in hand; **none is a
> setting, and none is a judgement** — ADR-0228 §2's framing binds entire, and so does its
> closing clause: *"Where any condition fails, the turn proceeds with the plan it has… No
> implementation retries a failed servicing, widens a request, re-asks the planner on a
> different prompt, or substitutes a read of its own for one the planner did not ask for."*

> **Normative.** **(a), (b), (c), (d) and (g) are ADR-0228 §2's own, verbatim and unamended.**
> (a) The turn's operation declares a planning budget (ADR-0228 §4). (b) The plan carried a
> `read_request`. (c) The request was serviced rather than declined under ADR-0226 §5's
> channel scoping. (d) The servicing completed. (g) The turn is within its operation's
> planning budget at the moment the check is made. **(d) is about the loop's own stage and not
> about what a source answered** (§2): a servicing that ran to its end and carries a typed
> failure satisfies (d), and one ADR-0226 §5 left partial does not.

> **Normative — a turn's first planner call is never gated.** These conditions govern a
> **further** call within a turn, exactly as ADR-0228 §2 governs a turn's second, and **every
> turn the owner starts makes its first planner call** whatever the attempt's ledger holds. An
> attempt whose planner-call allowance is spent still plans **once** per turn the owner starts
> and iterates no further; its investigation has stopped and its conversation has not. No gate
> in this decision takes a user's turn away from them, which is the standing rule of
> 2026-09-12 binding here in terms — convenience alone never justifies a user-facing
> restriction — and the count is then bounded by how many times the owner asks, which is
> ADR-0247 §5's own ground (§11).

> **Normative.** **`AttemptEffort.planner_calls` counts every call the attempt makes, a turn's
> first included**, so (f′) is a comparison against the whole ledger and not against a
> per-turn subtotal.

> **Normative — the allowance is an admission threshold on iteration and never a total count,
> and no clause of this decision claims otherwise.** An attempt whose ledger is at or past its
> allowance makes one further call for each turn the owner starts, so its total is bounded by
> **how many times the owner asks** and by no figure this ADR sets. The same holds of the
> working allowance: (h) admits or refuses a round, and an attempt spanning many turns may
> accumulate `working` well past PT3M one ungated first call at a time. **What the two figures
> bound is how far one owner act may be carried**, which is what §11(b) claims and the whole of
> what any clause here claims.

> **Normative — (f′), which supersedes (f).** **The attempt has made fewer `Planner.plan`
> calls than its kind's declared planner-call allowance (§5).** ADR-0228 §2(f) reads *"The
> **turn** has made fewer planner calls than §3's bound"*; the counter becomes the
> **attempt's** `AttemptEffort.planner_calls` and the bound becomes the attempt kind's
> declaration. Nothing else about (f) moves.

> **Normative — (j), new.** **The attempt's `phase` is `AttemptPhase.INVESTIGATE`.** An attempt
> whose phase has advanced past it makes its turn's one planner call and **does not iterate**:
> iterating there would either run the loop in a phase §1 does not place it in, or move the
> phase backwards, which ADR-0249 §6 forbids. **How a later turn's planning relates to an
> attempt that is authorizing, executing or verifying is A7's and A9's** (§14), and this
> decision decides none of it beyond declining to investigate there. **A round refused by (j)
> records `NOT_ITERATED` and sets no composing flag**, exactly as a round refused by (a) to (e)
> does today: ADR-0228 §9 makes `NOT_ITERATED` the record's default for a turn on which no
> revision was admissible, and ADR-0228 §10's carrier is reserved for a turn that stopped at a
> **guard** while still asking.

> **Normative — (h), new.** **The attempt's `AttemptEffort.working` is strictly less than its
> kind's declared working allowance *less the reserve* (§5, §6).** Checked with the injected
> clock (ADR-0026), immediately before each additional planner call and at no other point; at
> exactly the figure, and beyond it, the loop stops and records **working allowance reached**.
> The boundary instant is spent, not available — ADR-0228 §4's own posture, and for its own
> reason, that *"an injected clock makes equality an ordinary case in a test rather than a
> measure-zero curiosity."*

> **Normative — (i), new.** **The attempt has not just completed its second consecutive
> unproductive round** (§7). Where it has, the loop stops and records **unproductive**.

> **Normative — (e) is dissolved.** ADR-0228 §2's condition (e), as ADR-0240 §6 amended it,
> is **removed from the list**: a servicing that completed admits a further round whatever its
> typed outcome, and it is (f′), (g), (h), (i) and (j) that bound the sequence rather than (e).
> §2's
> **all-of-them** rule and its **if-and-only-if** form bind entire over the list as it now
> stands.

> **Normative.** **No outcome authorises a retry, and that is discharged by ADR-0228 §2's
> closing clause rather than by (e).** That clause binds verbatim — the **loop** never
> re-issues, widens or substitutes a read, whatever came back — and the distinction it draws is
> between the loop and the planner: **the loop initiates no retry of its own, and a request the
> planner authored is serviced under §7 whatever it resembles.** A further round is a further
> **plan**, and what the planner does with it is its own composition (ADR-0240
> §6: *"The broadening is the planner's and never the loop's"*).

**Dissolving (e) is the substantive change of this decision and it is paid for rather than
waived.** (e)'s own words are *"a planner called twice over one input is being asked the same
question twice at the price of a model round trip"*, and ADR-0240 §6 answered that worry for
one case by pairing the amendment with a carrier: *"Without §7 this section would be exactly
what (e) forbids."* §3 above generalises that carrier to every outcome, so the second call is
**never** over one input: it is over the same supply **plus** a statement of what each ask
returned, which is a fact the first call did not have and could not have derived. Where
ADR-0240 §6 could say that only of an empty structured read, this decision can say it of a
refusal, a failure, an expiry, a truncation and a duplicate.

**What (e) was also buying, and what replaces it.** (e) guaranteed that a round never followed
a round that learned nothing. §7's progress tests give that up in exchange for **one** such
round — the one #2169's *"justified alternative"* needs — and take it back at the second. The
trade is stated as a figure rather than as a hope: one unproductive round is admissible, two
consecutive ones stop the attempt.

**Adding to the list rather than reopening the list's discipline.** §2's demand that every
condition be *"a fact the turn already has in hand"* is the clause that keeps the second call
from becoming a policy, and (h), (i) and (j) meet it exactly: (h) is a comparison of two
durations under an injected clock, (i) is a count of consecutive rounds that admitted no record,
and (j) is an equality test on a stored enum member.
Neither reads a setting, and neither asks a model anything.

### 5. The allowance: `AttemptKind`, the ledger's own key, and figures that live in code

> **Normative.** `core/types.py` gains **`AttemptKind`**, a `StrEnum` valued by lower-cased
> member name and **closed at exactly two members**: `CONVERSATIONAL` and `SPOKEN`. The
> vocabulary is **added to and never renamed**.

> **Normative.** **`AttemptEffort` gains exactly one further member**, under the licence
> ADR-0249 §5 grants by name: **`kind`, an `AttemptKind | None`, defaulting to `None`**.
> `None` means **the turn that opened this attempt declared no operation**. `AttemptEffort`'s
> other two fields, their types, their `ge=0` bounds and their monotonicity are ADR-0249 §5's
> and are unchanged; **`GoalAttempt`'s field enumeration is not touched**, and no field is
> added to it.

> **Normative.** **The kind is stamped once, by `orchestration`, at the instant the attempt is
> opened, from the `ConversationalOperation` of the opening turn**: `CONVERSE` and
> `CONVERSE_STREAMING` stamp `CONVERSATIONAL`, `CONVERSE_SPOKEN` stamps `SPOKEN`, and a turn
> that named no operation stamps `None`. **It is never re-stamped, never derived at read time
> and never taken from a later turn's operation.** An attempt opened by a `converse` turn
> keeps its allowance when a `converse_spoken` turn later engages the same goal, and the
> reverse.

> **Normative — what each kind declares.** `CONVERSATIONAL` declares a **planner-call
> allowance of 4**, a **working allowance of PT3M** and a **reserve of PT30S** (§6), so its
> investigation gate (§4(h)) is at **PT2M30S**. **`SPOKEN` declares none, and so does
> `None`.** **An attempt kind that declares no allowance does not iterate**, whatever its
> audience, and its attempt makes exactly one planner call per turn exactly as the tree does
> today for an operation absent from `_PLANNING_BUDGETS`.

> **Normative — membership is the declaration.** The declarations live in **one mapping keyed
> on `AttemptKind`**, read with a `None` default and never as a branch with a figure at the
> end of it. ADR-0228 §2(a)'s rule binds verbatim one level up: *"no implementation reads an
> absent declaration as a default, as unknown-and-therefore-permitted, or as a case to decide
> at run time from anything other than a declaration."* **`SPOKEN`'s absence from the mapping
> is itself a decision; every future member's absence is an accident, and both fail closed.**

> **Normative.** **The figures are not `Settings` values, not deployment flags and not
> per-request parameters.** ADR-0228 §3's non-configurability binds entire and is the clause
> this decision rests on: *"a plan count is a count of model calls, so a configurable one is a
> configurable per-turn cost with no ceiling anyone reviewed."* The figures move only by the
> ADR that moves them.

> **Normative.** **What crosses the seam is the kind, never a figure.** ADR-0228 §4's
> construction is applied one level up in its own words — *"what crosses the seam is the
> operation's identity rather than a duration"* — so no caller, and no field of any `core`
> model, carries a limit. `AttemptEffort.kind` is a member of a closed enumeration whose
> allowance an ADR ruled; a `timedelta` or an `int` limit stored beside the consumed figure
> would be *"a figure a caller can contradict"*, which is the construction ADR-0228 §4
> refuses by name.

> **Normative.** **ADR-0228 §4 is kept entire and is not re-keyed.** `converse` and
> `converse_streaming` still declare **PT20S** from the turn's entry into the loop;
> `converse_spoken` still declares none; the budget is still checked with the injected clock
> immediately before each additional planner call; it is still a gate on **starting** a call
> and never a cancellation of one in flight; and it is still keyed on the operation and never
> on the channel's audience. **Both gates bind, and a further round is admitted only while
> every gate admits it** (§4).

**Why §4's key does *not* move to the attempt, against the design direction, and the reason is
ADR-0250 §12.** The direction taken into this lane was that ADR-0228 §4's key moves from
`ConversationalOperation` to the attempt. It cannot, because an attempt **spans turns**:
ADR-0250 §12 rules that *"a turn that associates to a goal whose attempt is non-terminal opens
none"*, so turn 2, turn 3 and turn 7 of one conversation about one goal all run inside the
attempt turn 1 opened. PT20S is a duration *"from the turn's entry into the loop"*; re-keyed on
the attempt it would be compared against `AttemptEffort.working`, which on turn 3 already holds
turns 1 and 2 — so it would be the same figure checked against a different quantity, and it
would fire on the second turn of every real conversation. The honest reading is that ADR-0228
§4 measures **one user's wait** and the attempt's allowance measures **one attempt's
consumption**, and that these are two quantities with two jobs. Both are kept, each where its
argument holds.

**Four, and what the figure is read off.** It must exceed two, because #1908 requires *"an
investigation that requires more than two decision rounds"* and #2169's acceptance scenario is
*"The test requires more decision rounds than the current two-call bound permits."* Three
would satisfy the letter and not the shape: the obligation asks for an investigation that
*"chooses a later operation from newly discovered evidence"*, which needs a round to ask, a
round to see and ask again **from** what came back, and a round to act on what that second ask
discovered. Four gives those three and one more that **plans over** the third read's yield
rather than merely composing over it. ADR-0228 §8's replay is the nearest measured shape this
corpus has — *"311/349 need **exactly one** belief, 29 need two, 9 need three"* — and three
levels covers the whole of that oracle set; four planner calls is the smallest bound that
reaches the third level and still plans over it. **This is a first declaration and is labelled
as one.** ADR-0228 §3 read its own two off a replay of a different quantity, and nothing in
this repository measures how many rounds an investigation needs. §7's extended stop
distribution is what turns it into a measurement, exactly as ADR-0228 §4 made PT20S one.

**PT3M and PT30S, and what relation they are chosen to keep.** ADR-0228 §4 states the relation
between its two guards — *"the count in §3 is meant to be the binding guard in the ordinary
case and the budget to be the tail guard for a turn whose first phase already ran long"* — and
these figures keep it one level up: the planner-call allowance is meant to bind in the ordinary
case and the working allowance to be the tail guard for an attempt whose rounds ran long or
whose turns were many. PT3M is the smallest round figure that admits four rounds and their
servicings across several turns without the tail guard firing in the ordinary case. PT30S for
the reserve is anchored on the one judged figure this corpus has for a model round trip on this
path — ADR-0228 §4's PT20S — plus headroom for the verification call A10 has not yet specified.
**Both are judged figures and both are labelled as such.** If the working allowance fires on a
large share of attempts, PT3M is wrong for the surface; if it never fires, the count is the only
guard and PT3M is inert. Neither is knowable before deployment, which is why the guard exists
**and** is instrumented.

**The kind is on the ledger rather than on the attempt, and that is a containment rather than a
convenience.** ADR-0249 §5 declares `GoalAttempt`'s fields *"exactly"* and grants a licence for
*"any further member of `AttemptEffort`"* and for nothing else; taking the licence that exists
avoids superseding a field enumeration that was ratified ten days ago and is being implemented
now. It is also the better home on its own merits: the kind's only consequence in this decision
is **which allowance the consumed figures are measured against**, and putting it on the ledger
means no component can hold a consumed figure without holding the declaration it is measured
against.

**Stamped at open and never re-derived, because an attempt whose allowance followed the
current turn's operation would have a budget the user could change by speaking.** A goal opened
in a browser and followed up by voice would have its allowance silently halved mid-attempt, or
a spoken attempt would acquire one by being typed at — and in neither case did anybody decide
anything. ADR-0249 §6's writer clause is the pattern: provenance is stamped by `orchestration`
at the instant it is true, and is never inferred at read time.

### 6. The reserve: the part of the allowance the investigation gate may not reach

> **Normative.** An attempt kind that declares a working allowance declares a **reserve**
> within it. The **investigation share** is the working allowance **less** the reserve, and
> §4(h) is checked against the investigation share alone. **Composing and verification are
> not gated on the attempt's allowance at all**: the working time they consume accumulates
> into `AttemptEffort.working` like every other working interval, and no clause of this
> decision stops them.

> **Normative.** **The reserve is not a second pool and nothing draws it down.** It is the
> part of the declared allowance the investigation gate is forbidden to reach. No
> implementation transfers time from the reserve to the investigation share, spends the
> reserve on a round, releases it when investigation finishes early, or admits a round on the
> ground that the reserve is untouched.

> **Normative.** **The reserve is stated over working time and over nothing else.** It takes
> no share of the planner-call allowance, because composing and verification make **no**
> `Planner.plan` call and a share of a count they cannot consume would be a figure with no
> referent; and it takes no share of spend, because spend is ADR-0194's and is not re-keyed
> here (§8).

> **Normative — what the reserve guarantees, and what it does not.** It is a **margin** and not
> a hard reservation, and the difference is stated rather than left to be discovered. §4(h) is
> a gate on **starting** a round, never a cancellation of one in flight, which is ADR-0228 §4's
> posture kept in its own words — *"a planner call already begun runs to its own completion, and
> a turn's total duration may therefore exceed its budget by one planner call and one
> servicing"* — so an attempt admitted at one tick below the investigation share may finish its
> round **past** the whole working allowance. **Two things are guaranteed and a third is not.**
> Guaranteed: the composing call **runs**, because it is gated on nothing; and **the round a
> given check admits overruns the investigation share by that one round and no more**, where
> without the reserve a check would have admitted a round up to the whole allowance and overrun
> from there. **Not guaranteed**: that `AttemptEffort.working` is below the working allowance at
> any moment, and in particular not when composing begins. The guarantee is over **one gate
> check** and is never a bound on the attempt's accumulated working time — §4's ungated first
> call means a long attempt may pass the allowance once per turn the owner starts, and §4 says
> so. No lane states, tests or renders either stronger claim.

> **Normative.** **A useful partial answer at exhaustion is a property of the reserve and never
> an instruction to a model.** No prompt, no rendered line and no `Settings` value asks for one.
> What the reserve buys is that an attempt which spent its whole investigation share **stops
> investigating with a composing call still to make**, and §7 is what gives that call something
> true to say.

**This is #2255's requirement as a mechanism, and the requirement is quoted rather than
paraphrased**: *"Preserve enough capacity to verify and report rather than spending everything
on repeated investigation."* #2170 states the same as an acceptance scenario — *"exhaustion
yields a supported partial answer"*. An instruction in a prompt would be a request to a model
that the system had already made impossible to satisfy; a reserve makes the answer **reachable**
and leaves what it says to the composing stage, which is the division ADR-0203 and ADR-0228 §10
already draw.

**A margin rather than an enforceable reservation, because the alternative is the cancelling
deadline ADR-0228 §14 defers by name.** Guaranteeing that composing begins below the allowance
would mean abandoning a planner call in flight, which *"needs a cancellation posture for a model
call the turn has already paid for, and a rule for what a half-composed plan is"* — a second
decision, deferred there and not taken here (§14). What is available without it is the margin,
and the margin is worth declaring: at each gate check it converts an unbounded overrun into a
one-round one, and it costs nothing but a figure. What it does **not** do is bound the attempt's
lifetime working time, for the same reason no figure here bounds its lifetime call count (§4):
what bounds both is how many times the owner asks.

**Composing is ungated rather than given its own budget, because a budget on the composing call
would be a second place for a turn to fail with nothing to show.** The reserve's whole purpose
is that the answer happens; a gate that could refuse it would defeat the purpose it was declared
for. What bounds composing is what bounds it today — the operation, the deadline of the call
itself, and ADR-0194's ceiling on what the world may cost.

### 7. Progress and stopping: the fold, the run test, two new stop reasons, and what composing is told

> **Normative — productive and unproductive, folded once over the whole round.** A request may
> carry one ask of each `ReadKind` (ADR-0226 §2), so a round has as many outcomes as it had
> asks, and **the fold is a single disjunction over them: a round is productive where *any* ask
> of it admitted at least one record the supply did not already hold, counted after ADR-0226
> §7's deduplication, and unproductive otherwise.** A round that reached no ask at all is
> unproductive.

> **Normative.** **The fold is over records admitted and never over the member**, which is what
> keeps it total and free of the contradiction a member-based test carries: `TRUNCATED` is
> productive where it admitted a record and unproductive where it admitted none, and
> `RETURNED_RECORDS` is productive by construction. The test is a count and never a judgement
> about relevance, quality or usefulness.

> **Normative — the unproductive-run test (§4(i)).** The loop counts **consecutive**
> unproductive rounds. **At two, it stops** and records `UNPRODUCTIVE`. A productive round
> resets the count to zero. **The run is counted within one turn and starts at zero on each
> turn of the attempt**, and no implementation persists it.

> **Normative — there is no duplicate-ask refusal, and a repeated ask is serviced.** The loop
> refuses no `read_request` and no ask of one on the ground that the turn has asked for it
> before. A repeated ask is serviced under ADR-0226 §5, §6 and §7 exactly as any other, and its
> outcome is classified by §2 exactly as any other — ordinarily `DUPLICATE`, where its every
> record deduplicates out.

> **Normative.** **No implementation compares one ask with another to decide whether to service
> it**, under any spelling: not by `ReadAsk` equality, not by a normalised form of one, not by a
> composed query, and not by a resolved label set. ADR-0228 §2's closing clause binds verbatim
> and is what this rule keeps — *"No implementation retries a failed servicing, widens a
> request, re-asks the planner on a different prompt, or substitutes a read of its own for one
> the planner did not ask for"* — and suppressing a read the planner **did** ask for is the same
> clause read from the other side.

> **Normative.** ADR-0228 §3's rule that the last plan's request *"is serviced under ADR-0226
> §5, §6 and §7 **exactly as the first plan's is**"* therefore binds verbatim and has no
> exception in this decision.

**A refusal here was drafted and then removed, and the reason is worth recording so no later
lane re-derives it.** The tempting argument is that ADR-0228 §7 makes the supply monotone within
a turn, so a byte-identical ask cannot add anything and servicing it is a guaranteed-wasted
store or provider call. **Monotonicity is a property of the supply and not of the source**, and
every kind breaks the inference for its own reason:

- **`WEB_SEARCH`** carries no argument at all. ADR-0231 §1 gives the ask *"no field"* because
  *"the query a search sends is composed by a `QueryComposer` from the turn's own utterance"*, so
  every such ask is byte-identical to every other and equality establishes nothing.
- **`CITATION_HOP`** carries labels, and a label is an ordinal into **the sequence passed on that
  call**. ADR-0228 §8 rules that *"The same label string may name different records on a turn's
  two calls, and that is the scheme working rather than a collision to repair"*, and that a
  record an earlier servicing fetched *"stands in the supply, is labelled on the second call, and
  its own `Provenance.evidence` is reachable by a `CITATION_HOP` the second plan emits"*. The
  identical ask is precisely how the second level is reached.
- **`STRUCTURED_READ` and `SIGHTED_QUERY`** run under a limit that depends on what the other
  asks of their request consumed: ADR-0226 §6 and ADR-0240 §5 split ten slots across kinds, so an
  ask that received two behind two other kinds and an identical ask alone in a later round are
  two different reads.
- **And every kind, against a store that moved.** ADR-0113 §5 states it and ADR-0226 §6 inherits
  it by name: *"This ADR adds no multi-band snapshot and **no cross-call read consistency of any
  kind**"*, and ADR-0226 §6's own test note says *"no test asserts that a concurrently-written
  store does"*. A record written between two of a turn's reads is exactly what the second read
  would find.

**So the refusal had no sound ground for any kind, and the honest form of the obligation is the
outcome rather than a suppression.** #2169 asks that duplicates be **distinguished** — *"Define
the planner-visible outcomes of success, empty results, duplicates, refusal, failure, and
truncation. Preserve their distinct meanings"* — which `ReadOutcomeKind.DUPLICATE` does, and
#2170 asks that repeated unproductive work be **detected and stopped**, which the unproductive-run
test does. Neither asks that a read the planner asked for be refused unread, and a loop that
refused one would be deciding, on a comparison it cannot make soundly, that the planner's
judgement was redundant.

> **Normative — the no-new-record test.** A round whose servicing added no record to the
> supply is unproductive by the clause above and is counted by the run test. **It is not by
> itself a stop.** ADR-0228 §2(e) made it one; §4 dissolves (e), and one such round is
> admissible precisely so that the planner can take the *"justified alternative"* #2169 names.

> **Normative — exhaustion.** Reaching the planner-call allowance (§4(f′)) or the investigation
> share (§4(h)) stops the attempt's investigation with the corresponding stop reason. **Neither
> is a failure, neither is a blocker (§9), and neither ends the goal.**

> **Normative.** **`orchestration`'s `StopReason` gains two members and closes at seven**:
> `WORKING_ALLOWANCE_REACHED` and `UNPRODUCTIVE`. This supersedes ADR-0228 §9's closure at five
> **in that count alone**. Every existing member keeps its name, its
> value and its meaning; `NOT_ITERATED` stays the default and stays the answer for an attempt
> that never reached a first plan; `BOUND_REACHED` keeps its name and its value and its subject
> becomes the attempt's declared planner-call allowance (§5); `BUDGET_REACHED` is unchanged and
> stays ADR-0228 §4's per-turn budget. **The vocabulary is added to and never renamed**, and no
> implementation, setting or later lane adds an eighth without the ADR that decides it.

> **Normative.** **The stop reason is `orchestration`'s, is derived from typed values, and is
> never a turn outcome.** ADR-0228 §9's clause binds verbatim: *"It is a stop reason and never
> a turn outcome. The original failure propagates unchanged."* No model output sets one.

> **Normative — the audit.** ADR-0226 §9's record, as ADR-0228 §9 extended it, is **extended
> again and not replaced**. Its per-servicing sequence keeps every field's meaning; its
> turn-level fields gain the **attempt's `AttemptKind`**, the attempt's **consumed planner
> calls**, the attempt's **declared planner-call allowance**, and the **`ReadOutcomeKind` of
> each servicing** as one more per-servicing field. ADR-0226 §9's counts-and-kinds rule binds
> the extension **entire**: the record still copies no text — no query, no label, no ask, no
> `content` span, no excerpt — carries **no plan identifier** and no identifier but the ambient
> correlation id, and carries no timing figure that would let a query's latency be attributed
> to a record. The **stop distribution** over the wider vocabulary is the instrument that
> revises §5's figures, and ADR-0226 §8's prohibition on reporting precision or recall from
> this record alone binds it.

> **Normative — what composing is told, and it is ADR-0228 §10 unchanged.** On an attempt
> whose investigation stopped **while its last plan still carried a `read_request`** — at the
> planner-call allowance, at the investigation share, at the per-turn planning budget, or on
> the unproductive run — the composing stage is given **the bare fact that
> the turn stopped looking while it was still asking**, and composes an answer that says so.
> On every other turn it is given nothing and the assembled prompt is byte-identical.
> **ADR-0228 §10 binds entire and gains no field**: the fact carries **no count, no duration,
> no guard name, no stop reason, no query and no label**; it is carried inside
> `ai_assistant.orchestration` as data, adds no field to a `core` type and no member to a
> Protocol; it is never inferred at the render site; and no lane renders it through the step
> account.

**Four tests and not a judgement, because #2170 draws the line and this decision stays on the
mechanical side of it**: *"distinguish model judgments from deterministic limits."* Every test
above is a comparison of counts or of members of a closed vocabulary. What is **not** decided
here is whether the material the loop gathered is *sufficient* — that stays where ADR-0176
leaves it, with the planner, which may return a plan carrying no `read_request` at all, and
ADR-0228 §2(b) then binds: no request, no round. **Sufficient-context restraint is the absence
of a mechanism rather than the presence of one**, and #2170's *"A sufficient-context task takes
no unnecessary read"* is that clause working. It is also why *"what is two plus two"* still
costs one planner call: the plan carries no request, (b) fails, and nothing about this decision
is reached.

**Two consecutive unproductive rounds, and why two is the figure rather than three.** Under
ADR-0228 §2(e) the figure is effectively **one** — the first unproductive round ends the turn —
so two is the smallest increment that changes anything, and what it buys is exactly the
scenario #2169 fixes in advance: *"An inaccessible source produces a justified alternative or
an honest stop."* One unproductive round gives the planner one chance to take a different route;
a second consecutive unproductive round is evidence that the route is not there, and a third
would be the loop reworking itself rather than converging. The alternative — letting the
planner-call allowance be the only stop — would spend four model calls on an attempt that
learned nothing after the first, which is precisely the *"repeated unproductive work"* #2170
asks be detected.

**The run resets at a turn boundary, and ADR-0052 §3 is why rather than a preference.** The
run is a claim about one continuous line of enquiry; a new turn carries a new utterance and may
carry a new interpretation revision, which is new information and honestly breaks the run. The
supply it was counted over is ephemeral in any case —
ADR-0052 §3's *"context and retrieved memories are ephemeral and were never persisted"* — so
persisting the count would mean persisting a claim about a supply nothing can reconstruct.
§14 defers the persisted variant with exactly that as what fires it.

**Telling composing nothing new is the conservative arm and it is chosen deliberately.** The
obligation asks that the reply *"says what was found and what was not"*, and composing already
holds what was found: it is the supply, in full, monotone across every round. What it does not
hold is that the system stopped while still asking, and ADR-0228 §10 already carries exactly
that — with an argument this decision does not improve on: *"A reply that named the deadline
would invite a retry, and a retry hits the same bound over the same supply; a reply that named
the count would be telling the user about the system's budget. Which guard fired is an
operator's question and §9 answers it."* More rounds do not make that reasoning weaker. **What
changes is which stops set the flag, and nothing else.**

### 8. Spend stays ADR-0194's, and the attempt gains no money field

> **Normative.** **The third quantity an attempt consumes is money, and this decision neither
> re-keys it nor copies it.** ADR-0194's ceiling binds unchanged, over the periods and in the
> currency it declares, admitted at ADR-0194 §3's invocation seam. **No attempt kind declares
> a spend allowance**, and **`AttemptEffort` gains no money field**.

> **Normative.** **A spend refusal reaches the loop as a typed read outcome and nowhere
> else.** `SearchRefusal.SPEND_REFUSED` and `SearchDisposition.SPEND_REFUSED` map to
> `ReadOutcomeKind.REFUSED` (§2), so the planner learns that a source would not answer and
> learns nothing about money — ADR-0242 §9's bar, which §2 restates.

**Three reasons, and the first is a data-rights one.** ADR-0194 §7 makes the total **derived**
— *"the total is derived, erasure resets it, and the period rolls over"* — so a durable
per-attempt money figure on a `PlanStore` row would be a **second** total of the same money, in
a second store, with an erasure obligation ADR-0194 §7 deliberately avoided by deriving. Second,
ADR-0194 §1 rules that *"**No ceiling configured means no ceiling**"* and puts the ceiling in
`Settings`, where a deployment decides it; a per-attempt-kind money figure fixed in code would
be a second, **non**-configurable spend policy, contradicting that design in the one domain
where the corpus has deliberately made the figure a deployment's choice — and this decision has
no measurement to set one from. Third, the loop does not need it: what the loop must do when
money runs out is stop asking that source and consider another, and `REFUSED` says exactly that.

**#2170's *"Record operations, planner calls, elapsed time and available cost figures"* is
discharged where each figure already lives.** Operations and planner calls are §7's extended
audit; elapsed is `AttemptEffort.working`; the cost figures are ADR-0194 §5's `SpendLedger`,
which already holds them per period and per invocation. §14 defers attributing that ledger to
an attempt, with what fires it.

### 9. `GoalStatus.BLOCKED`: the act, the writer, a three-limb test, and no reason that passes it here

> **Normative — the writer.** **`GoalStatus.BLOCKED` has exactly one producer:
> `orchestration`, at the site that writes `AttemptState.BLOCKED` on an attempt, in the same
> sequence.** No model output writes it, no inference writes it, no expiry, sweep, timer,
> reclaim or background pass writes it, and no lane infers it at read time.

> **Normative — the test.** That site writes the **goal's** status `BLOCKED` if and only if
> **all three** limbs hold of the blocker it is recording:
>
> 1. **It is not an exhaustion and not a progress stop.** No member of `AttemptEffort` running
>    out, and no stop reason of §7, satisfies this limb.
> 2. **Repeating the same request would meet the same blocker.** The blocker is a property of
>    the deployment or of the world, not of how much this attempt spent.
> 3. **What the blocker closed was *necessary* to the objective** — established against the
>    goal's own conditions and criteria, and never inferred from a route having closed. One
>    unavailable source establishes that one route is shut, not that it was the only one.
>
> Where any limb fails, **the attempt's state alone is written** and the goal stays `ACTIVE`.
> ADR-0249 §4's rule binds entire: *"an attempt may be blocked while the goal is `ACTIVE`"*.

> **Normative — and no reason available to this decision passes that test, so
> `GoalStatus.BLOCKED` gains no producer here.** This is stated rather than left to inference,
> exactly as ADR-0249 §4 states it for `ACHIEVED`. **Necessity is not a fact this decision
> holds**: it is a property of the goal's `conditions` and `criteria` (ADR-0249 §1), whose
> evaluation is A4's for sufficiency and A6's for prerequisites, and no clause of this ADR reads
> either. The nearest candidate — a `WEB_SEARCH` answering `SearchDisposition.NOT_CONFIGURED`
> on a turn whose reads admitted nothing — passes limbs 1 and 2 and **fails limb 3**: a request
> to summarise a note already in the assembled supply meets exactly that shape, and answers
> perfectly well. A predicate that wrote `BLOCKED` there would assert unreachability from the
> fact that one unnecessary route was shut.

> **Normative.** Later decisions name the reasons, each owing its own showing against all three
> limbs and a showing that its predicate is **evaluable from facts its writer holds** — §3
> persists no read outcome and ADR-0052 §3 leaves each turn's supply unreconstructable, so a
> predicate over an attempt's read history is a test nothing in the system can evaluate. **None
> of them is an exhaustion.**

> **Normative — exhaustion is never a blocker, and this is the clause the loop is written
> around.** An attempt that spent its planner-call allowance, its investigation share or its
> unproductive-run budget **stops investigating and leaves the goal `ACTIVE`**. It still plans
> once per turn the owner starts (§4) — so the objective is still achievable and nothing in the
> system is entitled to say otherwise. **This clause binds every later decision that names a
> reason**, and it is the one limb of the test that is closed here rather than deferred.

> **Normative — a superseded disagreement is never a blocker.** Where evidence rows disagree
> and one carries `EvidenceStanding.SUPERSEDED` (ADR-0249 §10), **the superseded row blocks
> nothing**: it is not counted toward any progress test of §7, it does not satisfy either limb
> above, and no attempt stops on it. **Which rows are superseded is A4's** (ADR-0249 §13); what
> is fixed here is that a row A4 marks superseded cannot block.

> **Normative — the write path and the rendering.** The status is written through
> **`PlanStore.set_goal_status`** — the member ADR-0250 §9 ratifies for it, not yet in the tree
> at `5c3bdd52` because that decision's implementation has not landed — and **no second write
> path is added** by this decision, which mints no `PlanStore` member of its own. **What a surface says about a blocked goal is not decided here**:
> ADR-0250 §15 owns what the surfaces owe and §14 owns how a pause is disclosed, and this
> decision adds no line, no vocabulary and no member to either.

> **Normative.** **`GoalStatus.ACHIEVED` and `GoalStatus.ABANDONED` gain no producer here.**
> `ACHIEVED` is A10's (ADR-0249 §4) and `ABANDONED` has exactly one producer already —
> `abandon_goal`, ADR-0250 §12 — and no clause of this decision writes either.

**`BLOCKED` means what ADR-0249 §4 says it means, and the test is that sentence made
mechanical**: *"`BLOCKED` on the goal means *this objective cannot currently be achieved*."*
An exhausted allowance says the system **stopped looking**, which is a fact about spending and
not about reachability; writing `BLOCKED` from it would assert the objective unreachable on the
evidence that nobody finished trying. That is the same circularity ADR-0249 §4 refuses for
`ACHIEVED` — *"producing a reply never by itself establishes that a goal was achieved"* — read
from the other end, and refusing both is what keeps the status vocabulary worth reading.

**What ADR-0249 §4 asked of A3 is the *act*, and the act is what this section fixes.** The
clause reads *"which act writes each is A2's and A3's respectively"* — ADR-0250 §12 answered
A2's by naming `abandon_goal`, and this section answers A3's by naming the site, the writer, the
write path and the test any reason must pass, and by ruling that **no exhaustion ever passes
it**. What it declines to do is invent a reason, and declining is the honest outcome rather
than a gap left open: a producer that fired on a closed route would make `BLOCKED` mean
*"something did not work"*, which is a state the attempt already records and which the goal's
disposition is explicitly not (ADR-0249 §4).

**A blocker vocabulary is also not minted here, and for ADR-0249 §10's reason.** Most blockers a
real attempt meets arise in authorization (A6) and in execution (A8, A9): a permission nobody
granted, an effect that cannot be resolved, a prerequisite absent. Each of those lanes holds the
necessity limb 3 asks for, because each is about something the plan *required*. A vocabulary
ratified here would be names for conditions this decision cannot produce — *"a `GoalEvidence`
whose fields all said 'A4 decides' would be a type ratified with no content"* — and the first
lane that could produce one would have to reopen it.

**And this costs nothing, which is worth stating plainly.** `GoalStatus.BLOCKED` has never been
written by anything in `src/`; declining to add a producer changes no behaviour at all. What it
buys is that the one member whose meaning is *"this objective cannot currently be achieved"* is
never written by something that only knows a read came back empty.

**Correction 1 lands as a prohibition rather than as a rule, which is all this lane may
take.** The owner's correction reads: *"Refreshed evidence needs supersession rules, so
retained historical disagreements do not permanently block progress."* The **rules** are A4's;
what this decision owes, and gives, is that the loop's own progress and blocking tests cannot
be the thing that makes a superseded disagreement permanent.

### 10. Which user acts open an attempt: none beyond ADR-0250 §12's three

> **Normative.** **This decision names no further attempt-opening act.** The closed set is
> ADR-0250 §12's three, unchanged: a turn that opens a goal, a turn that reopens a closed goal,
> and a turn that associates to an open goal with no runnable attempt.

> **Normative.** **The investigation loop opens no attempt.** No round, no revision, no
> recorded understanding, no stop, no exhaustion of any counter, no unproductive run and no
> resumption of a stopped investigation opens one. A stopped
> investigation is resumed, where it is resumed at all, **inside the attempt that ran it**, on
> a further turn of the user's own.

**This is ADR-0249 §5's prohibition taken at its word rather than worked around**: *"No
implementation opens an attempt in order to obtain a fresh allowance."* A fourth opening act
invented by the decision that also sets the allowance would be exactly that — an attempt
boundary the loop could mint is an allowance the loop could refresh, and the prohibition would
survive only as a sentence. ADR-0250 §12's own framing anticipates this: *"**A3 may name
further acts for the investigation loop and may name none that is not a user act**"*. The
honest answer to a licence whose only use would be to defeat the rule that grants it is to
decline it.

**And the report's §J.3 does not survive ADR-0250 §12, which is recorded here rather than
followed.** Revision 1 of #2255's report names *"a goal reopened after termination, a
clarification answered, an authorization supplied"* as the three opening events. ADR-0250 §12
fixes three different acts and rules in terms that *"**An answer to a clarification opens
none**"*, and it is ratified. The ratified text governs.

### 11. ADR-0247 §13's answer: no attempt advances without an owner act, and no per-conversation bound returns

> **Normative — (a).** **No attempt advances without an owner act.** An attempt moves only
> inside a turn the owner started or an act the owner performed — an answer, an approval, a
> denial, a withdrawal, a cancellation, an abandonment. **Nothing schedules, sweeps, resumes,
> retries or continues an attempt on a timer, at startup, or in a background job**, and no lane
> reads this decision, or any clause of it, as preparing for one.

> **Normative — (b).** **The expansion is bounded per attempt by a declared allowance** (§5),
> so the number of provider calls one owner act can cause is a **reviewed figure** — at most
> the attempt kind's planner-call allowance, each round drawing at most ADR-0226 §6's ten
> records, each search bounded by ADR-0241 §1's deadline and ADR-0231 §5's result and byte
> ceilings, and the whole bounded by ADR-0194's spend ceiling where one is configured.

> **Normative — (c).** **Therefore no per-conversation bound on searching is reintroduced, in
> any form.** `Settings.search_calls_per_conversation` stays removed, `ConversationSearchDraw`
> stays removed, `ConversationStore` regains no member, `SearchDisposition` regains no
> `NOT_ADMITTED`, and **no per-conversation quantity of any kind is substituted**. ADR-0247
> §5's per-conversation clause binds **verbatim**: *"**Per conversation: nothing bounds the
> number of searches**, and that is the decision rather than an omission."*

> **Normative — (d).** **No superseded prompt is restored and no search authority is
> widened.** Nothing in this decision restores a prompt, a ruling, a lineage floor, a coverage
> exception or a condition ADR-0247 §§3, §4 or §6 retired; nothing extends what a configured
> provider may be told; and no `ReadKind`, ask, destination or recipient is added or widened.

> **Normative — (e).** **What would fire a per-conversation bound again** is the remainder of
> the owner's own trigger: **batching**, and **unattended work**. Each falsifies *"every turn is
> owner-initiated"*, which is what ADR-0247 §5 rests on and what (a) above keeps true through
> this expansion. **ADR-0238 §16's rolling-window entry and its per-conversation elapsed-time
> entry stay exactly where ADR-0247 §13 restated them** and are neither discharged nor narrowed
> here.

**The trigger is quoted and each limb is answered separately, because two of the three are
untouched.** ADR-0247 §13 reads: *"Fired by the owner's own trigger, quoted: 'Revisit if planner
passes, batching or unattended work expand.' Each of those falsifies 'every turn is
owner-initiated', which is what §5 rests on."* Planner passes expand here — from two per turn to
four per attempt — so the trigger fires and this decision owes the answer. **But the expansion
does not falsify the sentence §5 rests on**, and that is the whole of the answer: every round of
every attempt still happens inside a turn the owner started, and (a) makes that a rule rather
than an accident of what has been built. What changes is how much one owner act may cause, and
that is bounded by a reviewed figure rather than by a per-conversation counter.

**A per-conversation cap would also be the wrong instrument for the risk that actually
expanded.** ADR-0247 §5's removed budget counted **searches per conversation**; what this
decision expands is **planner calls per attempt**, and a conversation may hold many goals while a
goal may span many conversations. A cap on the first would bind hardest on the user who asks a
lot of unrelated easy questions and not at all on the one attempt that loops — which is the
failure mode, backwards. The allowance binds on the unit that actually consumes.

**And the standing rule of 2026-09-12 forbids the lazy version of this answer.** *Convenience
alone never justifies a user-facing restriction.* A per-conversation cap reintroduced "to be
safe" against an expansion that is already bounded per attempt would be exactly such a
restriction: the owner would lose searches they asked for, in a conversation that did nothing
wrong, to buy a guarantee §5's own ground already gives.

### 12. The writer clauses

> **Normative.** **Every value this decision mints is `orchestration`'s, derived from typed
> values, and no model output sets any of them.** That is: each round's `ReadOutcomeKind` and
> the `ReadOutcome` carrying it; the stop reason; `AttemptEffort.kind`, `planner_calls` and
> `working`; the goal's `BLOCKED` stamp and the attempt's `AttemptState`; and the fact told to
> composing.

> **Normative.** A planner envelope that comes back carrying a read outcome, a stop reason, an
> effort figure, an attempt kind or a status has those values **discarded silently** — not an
> error, not a park, not a degradation of the turn. ADR-0249 §6 takes exactly this posture for
> a phase and a revision stamp, ADR-0228 §5 for a `supersedes` a planner supplied, and ADR-0226
> §3 for a label a model invents.

> **Normative.** **`AttemptEffort.planner_calls` is incremented once per `Planner.plan` call,
> immediately *before* the call and after the capability vocabulary is read, and it is counted
> whether or not the call returns.** A call that raises, that is cancelled, or that the turn
> does not survive is a call the attempt made and a call its allowance paid for; a ledger
> advanced on return would let a recovery re-invoke a planner past an allowance already spent.
> **This is the tree's existing discipline and not a new one** — `loop.py`'s `_planned` already
> advances ADR-0228 §9's per-turn count on exactly that line, for exactly that reason — raised
> here to the durable ledger.

> **Normative — when the charge becomes durable is ADR-0249 §12's question, and that section
> answers it in two cases which this decision keeps apart.** It adds no persistence site, moves
> none, and supersedes no clause of §11 or §12.
>
> - **An attempt not yet written** — one this turn opened. §12 rules that *"An attempt is
>   **opened in memory** when the user act that opens it occurs, which is before the turn's first
>   planner call; it is **first written** at the one site §11 names… A turn that ends before that
>   site writes no attempt row, exactly as it writes no goal row and no plan row."* So the charge
>   is on the in-memory attempt, a replan, branch or recovery **within the turn** sees it and is
>   charged by it, and it reaches the store with everything else the turn produced. **A turn that
>   dies before that site charges nothing**, exactly as it records no goal and no plan.
> - **An attempt already written** — one an earlier turn persisted. §12 rules that *"after the
>   first write, every change goes through `commit_attempt`, in this turn as in any later one…
>   **Nothing buffers a transition**"*, and that clause binds this ledger as it binds every other
>   field of the attempt. So each charge is an `AttemptTransition` through `commit_attempt`,
>   under §12's compare-and-swap, **issued immediately and buffered for nothing** — a resumed
>   turn that made two calls and then died leaves the stored count advanced by two, and a later
>   turn resumes from there rather than from where the earlier turn began.

> **Normative — the commit precedes the call, and what it records is an *admission*.** The
> charge is the attempt taking a slot of its allowance in order to make a call, not a claim that
> a call completed. It is issued first because that is the only ordering under which a call that
> raises is charged, and §12's prohibition on claiming a result before it happened is stated over
> `outcome` — *"an attempt whose `outcome` is `ANSWERED` is written after the answer exists"* —
> where a call count is not a result.

> **Normative — a charge may therefore stand for a call that never started, and this decision
> permits it rather than promising otherwise.** A cancellation delivered while the commit is in
> flight, or a process that stops between the commit and the invocation, leaves the slot
> consumed and `Planner.plan` never entered. **The over-count is bounded by one per turn and is
> the conservative direction**, and no lane closes it: closing it would need the commit and the
> invocation to be one atomic act across a store seam and a model seam, which nothing in this
> corpus provides — ADR-0054's audit worker already establishes that a store call absorbs a
> cancellation until it physically finishes, so even the commit cannot be un-issued. **No lane
> re-invokes the planner after a cancellation to "use" a charged slot**, and none subtracts from
> the ledger to return one: ADR-0249 §5's monotonicity forbids the second in terms, and the
> first would carry work past a cancellation the caller asked for.

**Every error this section admits is in the same direction, and that is the property worth
naming.** A charge can stand for a call that never ran; a call can never run uncharged. An
allowance that over-counts stops an attempt slightly early and costs the owner a round they can
buy back by asking again; one that under-counts lets a failing turn hand the next turn a free
allowance, which is a loop with no ceiling. The corpus takes the same direction wherever it
cannot be atomic — ADR-0194 §2's *"an unknown price is never zero"* is the same choice about
money.

**The asymmetry between the two cases is ADR-0249 §12's and not this decision's, and it is worth
saying which way each errs.** A new attempt's turn that dies leaves nothing, so nothing is
evaded: the store never learned the goal existed either. A persisted attempt's turn that dies
leaves the ledger advanced, so a later turn resumes with less allowance than it started the
failed turn with — the conservative direction, and the one the ledger exists for. A design that
buffered the persisted case to match the new one would let a turn that raised four times hand the
next turn a full allowance, which is the hole this whole section closes.

> **Normative.** `working` is accumulated by `orchestration` at each round boundary from the
> injected clock (ADR-0026), excluding every interval spent waiting for the user. ADR-0249 §5's
> monotonicity binds entire: **no replan, branch, recovery or phase transition resets either,
> and no implementation subtracts from one.**

> **Normative.** **No component other than the loop holds a plan whose `supersedes` or
> `targets_revision` is the planner's**, and no component other than the loop holds an
> `AttemptEffort` whose `kind` is anybody's but the stamping site's. ADR-0228 §5's
> once-immediately-on-return discipline and ADR-0249 §8's are applied here unchanged.

**The writer clause is ADR-0228 §5's reason applied to five more fields.** *"An id a model
returned would be an unprovenanced value in a durable audit record."* A stop reason, an effort
figure and a status stamp are durable audit values in exactly that sense: they are the record of
**what the system spent and why it stopped**, and a model that could write them could write an
account of its own restraint. The read outcome is the sharpest case — a planner that could
declare its own last read `RETURNED_RECORDS` could keep the loop running past every progress
test this decision has.

### 13. Re-entry with the updated brief, and what a replan does not reset

> **Normative.** **A replan never resets an allowance.** A revision within an attempt consumes
> from the same `AttemptEffort`; so does a recovery, a branch, a phase transition and a later
> turn of the same attempt. No implementation resets a consumed figure, opens a fresh attempt
> to obtain one, or reads a new turn as a new allowance.

> **Normative.** **The loop re-enters with the updated brief.** Where a round's
> `PlannerOutput.understanding` was recorded, the next round's `GoalBrief` is the **new**
> revision's, and the plan that round returns carries `targets_revision` naming it (ADR-0249
> §8). No round re-hands an earlier round's brief, and no round plans against a revision a
> later one superseded.

> **Normative.** **A turn that engages a goal whose attempt is non-terminal continues that
> attempt**, with its consumed figures as they stand and its `kind` as stamped. ADR-0250 §12
> binds entire: such a turn opens no attempt.

**This is the owner's correction 3 and #2255's §J.3, and both are mechanisms this decision
already has rather than new machinery.** The brief is projected *"from the goal's current
interpretation alone"* (ADR-0249 §9) and the stale-target refusal lives in `commit_transition`
(ADR-0249 §8), so "re-enter with the updated brief" is the existing projection called again on
the current revision. And the ledger's monotonicity is ADR-0249 §5's, quoted above, which this
decision relies on rather than restates — the one thing it adds is that the **gates** read that
ledger, so the prohibition acquires a consequence.

### 14. What this decision does not decide, by name, each with what fires it

> **Normative.** This decision settles nothing about the following, and no lane cites it
> toward any of them. Each carries the condition that fires it.

- **Whether the figures of §5 are right.** Fired by §7's extended stop distribution over a
  real deployment: a working allowance that fires on a large share of attempts says PT3M is
  wrong for the surface; one that never fires says the planner-call allowance is the only
  guard. **Not fired** by a lane finding four restrictive, and **not** by a deployment wanting
  more reach — ADR-0228 §3's non-configurability binds the successor as it binds this one.
- **A per-attempt spend figure, and the attribution of ADR-0194 §5's ledger to an attempt.**
  Fired by an ADR that decides how a **derived** total is attributed to a durable row without
  a second copy of it, and that carries ADR-0194 §7's erasure obligation for the attribution.
  **Not fired** by a lane wanting a number on a record (§8).
- **Decomposition — several asks of one kind in one round.** ADR-0228 §14 defers it and this
  decision does not take it: the loop now gives the planner up to four asks of each kind
  **with sight of each earlier ask's outcome**, which is strictly more informed than *n* blind
  asks in one envelope, and admitting *n* would reopen ADR-0226 §6's budget split and
  cross-kind precedence. Fired by §7's audit showing that an attempt's asks are ordinarily
  facets of one compound question rather than follow-ups.
- **A cancelling deadline** — one that abandons a planner call in flight rather than declining
  to start one. ADR-0228 §14 defers it, ADR-0228 §4's gate-on-starting rule binds both of this
  decision's time gates, and this decision adds nothing to the deferral but a second overrun
  window. Fired by §7's record showing overruns large enough to matter.
- **The real-information reader decision 8 places alongside M32, and autonomous web research.**
  What this loop **needs** from such a reader is named and nothing is designed: a read whose
  non-yield is a member of a closed vocabulary mapping onto §2's seven, returned rather than
  raised (ADR-0231 §17's posture); a servicing that either completes or does not, with no
  partial state reaching the supply (ADR-0226 §5); a deduplication key so a second read of one
  source is a `DUPLICATE` rather than a fresh record (ADR-0226 §7); and a declared bound it
  runs under (ADR-0241 §1). Fired by that reader's own ADR. **Not fired** by this decision, and
  §11(a) binds any autonomous variant of it.
- **Every reason that writes `GoalStatus.BLOCKED`.** §9 fixes the act, the writer, the write
  path and a three-limb test, and names **no** reason that passes it, because limb 3 —
  necessity to the objective — is a property of the goal's `conditions` and `criteria` that no
  clause here evaluates. Fired by A6's, A8's or A9's own ADR, each of which holds a prerequisite
  the plan actually required, and each owing its showing against all three limbs and a showing
  that its predicate is evaluable from facts its writer holds. **Not fired** by a lane finding a
  source unavailable, and **never** satisfied by an exhaustion.
- **How a later turn plans on an attempt that is authorizing, executing or verifying** (§4(j)).
  This decision declines to investigate outside `INVESTIGATE` and decides nothing else about
  such a turn. A7's and A9's, with the plan-driving stage ADR-0228 §14 already defers.
- **What an attempt's `AttemptOutcome` is on exhaustion.** A10's (ADR-0249 §5, §13). §9 fixes
  only that the goal stays `ACTIVE`; which of `PARTIAL`, `UNCERTAIN` or another member the
  attempt earns is not settled here.
- **Evidence rows, their supersession and their conflict adjudication.** A4's (ADR-0249 §13).
  §9 fixes only that a row A4 marks `SUPERSEDED` cannot block.
- **A cross-turn carrier for read outcomes** (§3). Fired by an ADR that decides how a typed
  outcome becomes durable — which is a `PlanStore` widening, and is the same widening A4 is
  already taking for evidence rows (ADR-0249 §10), so the two are decided together or not at
  all. **Not fired** by a lane finding the turn scope narrow.
- **Persisting the unproductive-run count across a turn** (§7). Fired by an ADR that first
  decides what an attempt's ephemeral supply is reconstructed from, which ADR-0052 §3 says is
  nothing. **Not fired** by a lane finding the reset permissive.
- **A rolling window, or a per-conversation elapsed-search-time bound.** ADR-0238 §16's two
  entries, as ADR-0247 §13 restated them, stay exactly there and are neither discharged nor
  narrowed (§11(e)).
- **Whether ADR-0244 §3's one-open-park-per-conversation rule survives ADR-0247 §5.** Booked by
  the owner on 2026-09-12 as a separate contract review; untouched here, as in ADR-0249 §13.

### 15. Scope, and what this records against earlier ADRs

**This ADR partially supersedes four ratified ADRs, in seven scopes, and no others.** The
header carries each scope; this section shows ADR-0070 §1's test for every one, and shows why
the ADRs a reader would expect to move do not.

**ADR-0228 §2's condition (e) and the enumeration's completeness — superseded.** (e) reads
*"The servicing returned **at least one record the supply did not already hold**, counted after
ADR-0226 §7's deduplication"*, as ADR-0240 §6 extended it. §4 dissolves it and adds (h), (i)
and (j).
A reader holding only ADR-0228 would refuse a second round after a refused or empty read and
would admit a fifth round after four productive ones, and would not conform in either
direction — ADR-0070 §1's test coming out on the supersession side, twice. **Conditions (a),
(b), (c), (d) and (g) bind verbatim and are quoted in §4**; §2's all-of-them rule, its
if-and-only-if form, its *"a fact the turn already has in hand… none is a setting, and none is
a judgement"* framing, and its closing clause and the prohibition inside it all bind **entire**
and are load-bearing here.

**ADR-0228 §3's count and its subject — superseded.** *"A turn makes **at most two** calls to
`Planner.plan`"* becomes an **admission threshold on the attempt's iteration** rather than a
total on the turn: a further call within a turn is admitted only while `AttemptEffort
.planner_calls` is below the attempt kind's declared allowance, and a turn's own first call is
made whatever the ledger holds (§4). A reader holding only ADR-0228 would stop at two and would
not conform. **No clause of this decision replaces §3's total with another total**, and what
bounds an attempt's lifetime count is stated in §4 in terms: the owner's turns. **§3's non-configurability clause is not
superseded** — it is the clause this decision rests on, and §5 quotes it — and neither is its
servicing-the-last-request rule nor its stopped-at-the-bound rule, both of which bind over the
new figure. §3's *"the two figures differ by at most one"* is likewise unchanged in substance:
the attempt's reads and its plans still differ by at most one.

**ADR-0228 §9's five-member closure — superseded in that count alone.** The count becomes
seven. Every existing member keeps its name, its value, its meaning and its default;
`BOUND_REACHED`'s **subject** moves with §3 and its name does not. §9's one-record rule, its
extend-not-replace clause, its counts-and-no-copy rule, its per-turn fire-rate definition, its
*"not iterated" is the default* clause and its stop-distribution clause bind **entire** and are
extended by §7. A reader holding only ADR-0228 would refuse a sixth member and would not
conform.

**ADR-0240 §7's parameter declaration — superseded.** *"`Planner.plan` gains one keyword
parameter, `empty_reads: Sequence[ReadAsk] = ()`"* becomes `read_outcomes:
Sequence[ReadOutcome] = ()`. A reader holding only ADR-0240 would implement a parameter that no
longer exists and would not conform. **Every other clause of §7 binds verbatim** and §3 restates
each over the wider carrier: the ask carried back byte for byte and never edited, nothing the
store said crossing on it, a read the budget did not reach not being in it, `()` on the first
call, the separate-governance clause, and the breaking-change flag.

**ADR-0240 §6's narrowing to `STRUCTURED_READ` — superseded in one respect.** §6 rules that only
a structured read's emptiness reaches the planner, on the ground that *"Only a structured read
carries a certification about the owner's own records, so only a structured read supports the
inference the broadening rests on."* That ground is **unchanged and is not disputed**: it is a
statement about which emptiness licenses a *broadening inference*, and §2 of this decision
neither draws that inference nor invites it. What changes is that an empty read of any kind
reaches the planner **as a fact about that ask**, on a round that was admissible for its own
reasons. A reader holding only ADR-0240 would withhold a `WEB_SEARCH`'s `NO_RESULT` from the
planner and would not conform. **§6's definition of an empty structured read, its
deduplicated-out exclusion, its broadening-is-the-planner's clause, its bound clause and its
prohibition on citing ADR-0237 §7 all bind entire**, and the last is honoured here: no clause of
this decision cites ADR-0237 §7 as a ground for anything.

**ADR-0247 §5's per-turn sentence — superseded.** *"**Per turn**: ADR-0228 §4's planning budget
gates the start of each additional planner call, so a turn that declares one starts at most two
planner calls and therefore at most two searches"* — the figure two stops being true, because
§3's count moved. A reader holding only ADR-0247 would tell an operator that a turn runs at most
two searches and would be wrong. **§5's per-search, per-money and per-conversation clauses bind
verbatim**, its two-SQLite-columns clause is untouched, its dissolution of two ADR-0238
deferrals is untouched, and **§13's first deferral is answered rather than superseded** (§11) —
an answered deferral is the ADR that answers it recording the discharge, which §11 does and this
section records.

**ADR-0249 §7's parameter-preservation clause — superseded in the `empty_reads` term alone.**
§7 declares that `Planner.plan` *"keeps `context`, `memories`, `capabilities`, `files` and
`empty_reads` **exactly as they stand**"*. §3 of this decision replaces `empty_reads` with
`read_outcomes`, so a reader holding only ADR-0249 would implement a signature carrying a
parameter that is gone — ADR-0070 §1's test coming out on the supersession side, and a record
ADR-0082 §1 owes against ADR-0249 rather than against ADR-0240 alone. **The other four terms
are kept exactly as they stand**, and every remaining clause of §7 binds entire: the `GoalBrief`
first positional parameter, the required `utterance` keyword, the `evidence` keyword defaulting
to empty, the `PlannerOutput` return, the annotation clause, ADR-0211 §2's applied
keyword-parameters ruling, and `PlannerOutput`'s two-field enumeration with its
`None`-is-not-an-error clause.

**Nothing else in ADR-0249 moves, and it is the ADR a reader should check second.** This
decision exercises two licences that ADR grants by name — §5's *"A3 fixes the allowances, the
reserve and any further member of `AttemptEffort`"* and §13's deferral of the loop — and
**exercising a licence is not superseding the clause that grants it**. No field of `GoalAttempt`
moves, no member of `AttemptState`, `AttemptOutcome`, `AttemptPhase` or `GoalStatus` moves, §6's
no-backwards rule is relied on, §4's status semantics are relied on, §8's stale-target rule is
relied on and §9's projection is relied on. §4's *"which act writes each is A2's and A3's
respectively"* is **discharged** by §9 rather than amended: the clause said an act would be
named elsewhere, and it was.

**ADR-0250 is untouched.** §12's three attempt-opening acts stand, §10 names none more, and
§12's sentence *"A3 may name further acts… and may name none that is not a user act"* is
discharged by declining the licence. Declining a licence changes no clause.

**ADR-0226 is untouched**, and it is the one a reader would most expect to move. §5's channel
scoping, §6's budget of ten and its reserve of the count's movement, §7's deduplication and
append-never-interleave, §8's trigger and its rate, §9's record and its counts-and-kinds rule
and §3's namer rule and labelling all bind entire; §3's second-level clause was already
superseded by ADR-0228 §8 and is not touched again here — a fourth round reaches a fourth level
by exactly the mechanism ADR-0228 §8 ruled, *"a record the loop **chose to render**, labelled,
that a model then asked for"*, and by no other.

**ADR-0194 is untouched** (§8): no ceiling, no period, no currency, no countability rule and no
admission site moves, and no second total of the same money is minted.

**ADR-0241 is untouched**: §1's per-search deadline and §4's expiry-as-an-outcome bind entire,
and §2 preserves the second at the planning seam rather than folding it into a failure.

**ADR-0237 is untouched**, and §6 of ADR-0240 is why it must be said: that section rules that
*"No lane cites ADR-0237 §7 as the ground for this section"*, and no clause here cites it as a
ground for anything.

**ADR-0128, ADR-0231, ADR-0242, ADR-0244, ADR-0176, ADR-0211, ADR-0026 and ADR-0052 are
untouched.** `MemorySearchResult.capped` keeps its meaning and is read rather than changed;
every member of `SearchDisposition`, `SearchRefusal` and `FetchRefusal` keeps its name, its value
and its meaning and none is added or removed, so no vocabulary of ADR-0231, ADR-0242 or ADR-0244
moves; ADR-0176's decline envelope is relied on; ADR-0211 §3's re-read is relied on; ADR-0026's
clock is injected as it is today; and ADR-0052 §3's ephemerality is quoted as a reason rather
than changed.

### 16. The lane cut

> **Normative.** The implementation lands in **two lanes**, in this order, each a separate PR,
> and **both are sequenced behind ADR-0249's L1**, which mints `AttemptEffort` and `GoalAttempt`.
>
> - **L1 — the contract, at unchanged behaviour.** `core/types.py` gains `ReadOutcomeKind`,
>   `ReadOutcome` and `AttemptKind`, and `AttemptEffort` gains `kind`; `core/protocols.py`'s
>   `Planner.plan` swaps `empty_reads` for `read_outcomes`; `planning/planner.py` renders the
>   outcomes in place of the empty asks; the `Planner` conformance suite and the canonical fake
>   in `ai_assistant.testing` take the new parameter; every call site moves mechanically so the
>   tree type-checks against the shapes ADR-0249's L1 landed. **§2's classifier lands here**,
>   because the carrier cannot be filled
>   without it: `orchestration/loop.py` passes the outcomes of the reads it already services,
>   which on this lane are at most the two ADR-0228 §3's bound admits. **`AttemptEffort` gains
>   a field and it is reachable through `GoalAttempt` on the wire and in `PlanExport`, so L1
>   moves `PROTOCOL_VERSION` from 38 and `PlanExport.schema_version` from 8**, under ADR-0124
>   §9's rule that the bump rides the change that makes a peer's value invalid; it is the only
>   lane of this decision that moves any version. **No behaviour changes in L1**:
>   the bound is still two, no allowance is declared, no attempt kind is stamped, no progress
>   test runs and no stop reason is added.
> - **L2 — the loop.** `orchestration/` alone: §4's conditions and its never-gated first call,
>   §5's declaration mapping and the stamping site, §6's reserve, §7's progress fold, its
>   two stop reasons, audit extension and widened composing trigger, §9's `BLOCKED`
>   site, §9's three-limb test and its prohibition — which writes nothing, so the lane ships the
>   negative arms rather than a `set_goal_status` call — and §12's writer clauses including the
>   charge-before-the-call discipline.

> **Normative.** **L1 is the one sanctioned cross-subsystem lane**, and it is sanctioned by
> ADR-0137 §2 for the reason ADR-0249 §15 states one decision earlier: a `Planner.plan`
> signature change is not confinable to one package, because `core/protocols.py` declares it,
> `planning/planner.py` implements it, `ai_assistant.testing` fakes it and
> `orchestration/loop.py` calls it, and a PR moving fewer than all four does not type-check
> under `mypy --strict`. **L2 is one subsystem, and no other cross-subsystem pairing is
> authorised by this decision.**

> **Normative.** **ADR-0249's L1 has merged** (`5c3bdd52`), so both lanes have the shapes they
> extend. **Neither mints a stand-in for a type ADR-0249 already decided**, and neither reopens
> `GoalAttempt`'s field enumeration: L1 adds one member to `AttemptEffort` under the licence
> that type's own docstring carries, and nothing else of ADR-0249's surface moves.

### 17. The arms this decision owes

> **Normative.** The lanes owe representative-input tests for each of the following, on the
> real orchestration path with an injected clock and a fake planner whose returns are scripted.
> Each is one of #2169's or #2170's fixed acceptance scenarios or one of this decision's own
> guards, and **no arm is discharged by a unit test of a helper in isolation**.

1. **More than two rounds, choosing from discovered evidence.** An attempt whose round 1 read
   yields a record, whose round 2 asks a question composed from that record and yields another,
   and whose round 3 asks a third question composed from the second — four planner calls, three
   servicings planned over, and the third ask asserted to be one no earlier round could have
   composed. This is #2169's *"A later investigation step depends on a fact discovered after the
   initial search and fetch"* and it fails on `origin/main`.
2. **Each of the seven outcomes reaches the planner, distinguished.** Seven arms, one per
   `ReadOutcomeKind` member, each asserting the member the planner was handed and each driven
   from a real source vocabulary value rather than from a constructed `ReadOutcome`.
3. **The classifier is total over the four facts, not over enum membership.** Combinations, not
   members: a source non-yield of each class; a read returning records and admitting some;
   returning records and admitting none; returning none at all; each of those again with
   completeness uncertified; and the four no-entry cases — `StructuredOutcome.NOT_ASKED`,
   `StructuredOutcome.NO_SLOT`, `SearchDisposition.NO_BUDGET` and a servicing ADR-0226 §5 left
   declined or partial — asserted to produce **no** carrier entry.
4. **`capped` at the exact ceiling is not an assertion that more exists.** A read whose eligible
   set exactly meets the store's ceiling comes back `capped=True` (ADR-0128 §2) and is
   `TRUNCATED`; the arm asserts the planner is told completeness was not certified, that the
   round is **productive** where that read admitted a record and **unproductive** where it
   admitted none, and that nothing rendered or recorded claims further records exist.
5. **A source failure is a completed servicing.** A `WEB_SEARCH` answering
   `SearchRefusal.TRANSPORT_FAILED` satisfies ADR-0228 §2(d), reaches the planner as `FAILED`
   and admits a further round; a servicing ADR-0226 §5 left partial fails (d), produces no
   carrier entry, and admits none.
6. **Supply monotonicity binds a turn and is not claimed across turns.** Within one turn no
   record leaves the supply across four rounds; a second turn of the same attempt assembles its
   own three groups, is asserted to be permitted to differ from the first turn's, and inherits no
   fourth group — including across a restart between the two turns.
6a. **An attempt past `INVESTIGATE` does not iterate.** A later owner turn on a non-terminal
   attempt paused in `AUTHORIZE` makes its one planner call, is asserted **not** to service a
   further round however productive the first read was and however much allowance remains, the
   attempt's phase is asserted unchanged — never moved back to `INVESTIGATE` — and the turn is
   asserted to record `NOT_ITERATED` and to set **no** composing flag.
7. **Sufficient-context restraint.** *"What is two plus two"* — a plan carrying no
   `read_request` — makes **exactly one** planner call, services nothing, runs no progress test
   and records `NOT_ITERATED`. #2170's *"A sufficient-context task takes no unnecessary read."*
8. **Useful continuation.** An attempt whose first read is `REFUSED` and whose second, to a
   different source, is `RETURNED_RECORDS`: the round after the refusal is admitted, the run
   count resets, and the attempt answers. #2169's *"justified alternative"*.
9. **Unproductive repetition stops.** Two consecutive rounds admitting no record stop with
   `UNPRODUCTIVE` **before** the planner-call allowance is reached, and the planner is asserted
   **not** to have been called a third time. #2170's *"a repeated-result task stops before
   blindly exhausting the maximum."*
10. **The fold is over the whole round.** A round whose request carried several asks — one
    admitting a record and one `EMPTY` — is **productive** and resets the run; a round whose every
    ask admitted nothing is **one** unproductive round and never two, however many asks it
    carried.
11. **A repeated ask is serviced, never refused, and the arm is driven once per kind.** A plan
    re-emitting a byte-identical ask this turn already serviced is **serviced again** and its
    outcome classified by §2. Four cases, each asserting the read actually ran: two `WEB_SEARCH`
    asks on one turn — necessarily byte-identical, ADR-0231 §1 giving the ask no field — reach
    the composer twice; an identical `CITATION_HOP` over labels whose sequence grew is asserted
    to resolve to the record the earlier servicing appended and to reach **its** evidence, which
    is ADR-0228 §8's second level and is unreachable if the ask is refused; an identical
    `STRUCTURED_READ` whose first servicing ran behind two other kinds on ADR-0226 §6's split
    budget is asserted to admit records the first could not reach; and an identical
    `SIGHTED_QUERY` over a store written to between the two reads is asserted to admit the new
    record — ADR-0113 §5's *"no cross-call read consistency of any kind"*.
12. **A serviced duplicate is reported as one.** An ask whose every record deduplicates out is
    serviced, yields `ReadOutcomeKind.DUPLICATE`, reaches the planner as such, and counts as one
    unproductive round — the whole of what #2169's *"duplicates"* obligation asks for.
13. **A useful partial answer at exhaustion, and the margin's honest bound.** An attempt that
    spends its whole investigation share composes an answer over the supply it gathered, with
    `AttemptEffort.working` asserted to be at or past the investigation share at the moment
    composing is entered. A second arm drives the **overrun**: a round admitted at one tick below
    the investigation share whose planner call outlasts the reserve is **not** cancelled,
    composing **still runs**, and the test asserts that **that check** admitted one round and no
    more — and asserts **no** upper bound on `working`, because §6 claims none. A third arm drives
    two further owner turns on the same attempt past the allowance and asserts each is served, so
    that no implementation reads §6 as a cap. #2170's *"exhaustion yields a supported partial
    answer."*
14. **The boundary instants are spent, not available.** With the injected clock set to exactly
   the investigation share, no further round is admitted and the stop is
   `WORKING_ALLOWANCE_REACHED`; at one tick less, one is. ADR-0228 §4's own arm, one level up.
15. **Both gates bind.** An attempt inside its allowance whose turn has spent ADR-0228 §4's
    PT20S stops with `BUDGET_REACHED`; an attempt inside PT20S that has spent its planner-call
    allowance stops with `BOUND_REACHED`.
16. **A replan does not reset a counter, and a new turn does not.** An attempt's second turn is
    asserted to start from the `planner_calls` and `working` the first turn left. A second arm
    drives a turn on an attempt whose allowance is **already spent**: it makes **exactly one**
    planner call, iterates no further, records the stop, and the ledger is asserted to advance by
    exactly one rather than to reset.
17. **A call that raises is still charged, and the two persistence cases are separate arms.**
    (a) A planner call that raises leaves the in-memory `planner_calls` advanced, and a recovery
    **within that turn** is asserted to find the allowance already spent rather than to obtain a
    free call; a cancellation arm asserts the same. (b) A turn on an attempt this turn **opened**
    that dies before ADR-0249 §11's site writes **no** attempt row, so nothing of its ledger is
    durable and no second persistence site exists. (c) A turn on an attempt an **earlier turn
    persisted** that makes two calls and then dies is asserted to leave the **stored** count
    advanced by two, through `commit_attempt` under §12's compare-and-swap, and a later turn is
    asserted to resume from there — the arm that fails if any implementation buffers a
    persisted attempt's ledger to the turn's persistence site. (d) A cancellation delivered
    **while the charge commits** is asserted to leave the slot consumed with `Planner.plan`
    never entered, the planner asserted not to be re-invoked afterwards, and the ledger asserted
    not to be decremented — the conservative over-count §12's clause permits by name.
18. **The system opens no attempt to buy budget.** An attempt that exhausts its allowance is
    asserted to leave `GoalAttempt` count unchanged and the goal `ACTIVE`, with no second attempt
    row written by anything but one of ADR-0250 §12's three acts.
19. **An unpriced kind does not iterate.** An `AttemptEffort` whose `kind` is `SPOKEN`, and one
    whose `kind` is `None`, each make exactly one planner call per turn — the fail-closed arm,
    and the one a member added tomorrow inherits.
20. **The kind is stamped once.** An attempt opened under `CONVERSE` and engaged on a later turn
    under `CONVERSE_SPOKEN` keeps `CONVERSATIONAL`, and the reverse.
21. **Nothing writes `GoalStatus.BLOCKED`, and the near-misses are the arms.** An attempt that
    exhausts every counter leaves the goal `ACTIVE`; a turn whose `WEB_SEARCH` answered
    `NOT_CONFIGURED` and whose every ask admitted no record **also** leaves it `ACTIVE`, and the
    arm drives the case that makes limb 3 necessary — a request to summarise a note already in
    the assembled supply, which answers correctly on that same shape; `set_goal_status` is
    asserted not to be called with `BLOCKED` anywhere in this decision's lanes; and a superseded
    evidence row is asserted to block nothing and to reset no run count.
22. **The writer clauses.** A planner envelope carrying a read outcome, a stop reason, an effort
    figure, an attempt kind or a status has each value discarded silently, with the turn
    otherwise byte-identical.
23. **The negative arms of §11.** No scheduler, job, timer, startup hook or background task
    advances an attempt — asserted as an absence over the composition root and the hub's task
    set — and no `Settings` field, `ConversationStore` member or `SearchDisposition` member
    bounding searches per conversation exists.
24. **The audit says what the loop spent.** One record per turn, emitted once and conditioned
    on nothing, carrying the per-servicing `ReadOutcomeKind` sequence, the attempt's kind, its
    consumed planner calls and its declared allowance — and asserted to carry **no** query, no
    label, no ask, no excerpt and no identifier but the ambient correlation id. A second arm
    asserts the stop distribution is readable over all seven members.
25. **Byte-identical on every other turn.** A turn that did not stop while asking assembles a
    composing prompt byte-identical to the one it assembles on `origin/main`. ADR-0228 §10's own
    arm, kept.

### 18. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**ADR-0070 §1's test is *"would a reader acting on the ADR act identically before and
after"*,** and it comes out on the supersession side for all seven scopes of §15: a reader holding
only ADR-0228 stops at two planner calls, refuses a round after an empty read and refuses a
sixth stop reason; a reader holding only ADR-0240 or only ADR-0249 implements a `Planner.plan`
carrying a parameter that is gone, and the first of them also withholds a refusal from the
planner; a reader holding only ADR-0247 tells an operator a turn runs at most two searches. Each is a **new ADR that supersedes part of an old one**, which is
what §1 requires, and none is an in-place amendment.

**ADR-0082 §1's test is *"does the later ADR amend a named clause of the earlier one"*,** and it
is answered clause by clause in §15. A record is owed on **ADR-0228, ADR-0240, ADR-0247 and
ADR-0249** and on no other ADR: everything this decision adds to ADR-0226, ADR-0250, ADR-0194,
ADR-0241, ADR-0237, ADR-0231, ADR-0242, ADR-0244, ADR-0128, ADR-0176, ADR-0211, ADR-0026 and
ADR-0052 is a **stacked addition** — an obligation that contradicts no sentence those ADRs
wrote — *"recorded in the ADR that makes it, and nowhere else."*

**Each of the four records goes on the earlier ADR's `Status` line and in an appended dated
note, and every one of them is a *supersession* rather than an amendment**, so ADR-0082 §2's
leading-token exclusion — which is stated over an *amendment qualifier* and says in terms that
it is *"about the record's form, never about whether one is owed"* — does not reach any of
them. ADR-0228's line is already led by `Partially superseded by` and gains this ADR's pair
beside ADR-0240's, ADR-0242's and ADR-0249's. ADR-0249's line is already led by `Partially superseded by` — ADR-0250 put it there — and gains
this ADR's pair beside it. ADR-0240's and ADR-0247's lines each read
`Accepted` today and each take the leading token in its place, which is ADR-0001's rule and the
template's: *"the supersession leads and 'Accepted' is dropped (so a prefix match on 'Accepted'
cannot misread the replaced part as live)"*. All four take the appended dated note ADR-0070 §1
requires in every case.

**This decision is a contract ADR under ADR-0015 §5.** It changes `core/protocols.py` and
`core/types.py`, so it is reviewed while `Proposed`, ratified only after, and **merged as its
own PR before anything implements against it** (golden rule 5). It requires **both** review
lenses (ADR-0015 §1): the diff is prose, and the surface it decides is the contract one.

## Consequences

**A conversational attempt may now cost four planner calls and four servicings rather than
two and two**, so the worst case of a turn inside such an attempt roughly doubles in latency
and in model spend. Two guards bound it and both are instrumented: the per-turn PT20S budget is
unchanged, so no single turn's wait grows without the operation's own gate admitting it, and
the attempt's working allowance is the tail guard. Whether the trade is worth it is a number
§7's stop distribution produces from the first deploy rather than a claim made here.

**The planner learns why a read produced nothing, which is a new input and a new way to be
wrong.** A model told that a source refused may take a worse alternative than one told nothing;
the bet is that a typed vocabulary of seven, carrying no message and no ground, is a small
enough surface that the alternative it prompts is better on balance. The audit records the
distribution, so the bet is checkable.

**An attempt is now the unit that spends, and a long conversation about one goal shares one
allowance.** A user who asks five successive questions about one goal draws on one ledger, and
the fifth turn may find the allowance spent where the first did not. That is the design working
— the allowance is per attempt precisely so that a loop cannot buy more by taking another turn —
and §7's composing flag is what makes it legible rather than silent. A further user act that
opens a new attempt (ADR-0250 §12) gets a new allowance, and nothing the system does can.

**`GoalStatus.BLOCKED` still has no producer after this decision**, so every attempt that stops
leaves its goal `ACTIVE` with an attempt state that says what happened. That is a legible gap and
an honest one, and it is the same shape ADR-0249 §4 left `ACHIEVED` in: the alternatives were a
status claiming unreachability from an exhausted budget, or one claiming it from a source being
unavailable on a turn that could answer anyway. What this decision does supply is the act, the
writer, the write path, a three-limb test and the rule that no exhaustion ever passes it — so the
next lane to name a reason finds the frame already built and the wrong answers already closed.

**Two of `ReadOutcomeKind`'s seven members are unreachable on some deployments** —
`EXPIRED` needs a source with a deadline and `TRUNCATED` needs one that caps — and a deployment
with no search account reaches neither. The arms drive each from a real source value so that no
member is ratified with no producer; that a member is rare on one deployment is not a defect.

**The reserve is a margin and the ADR says so**, so an operator reading `AttemptEffort.working`
will sometimes see a figure past the declared working allowance — by one round per gate check
that admitted one, and once more for each turn the owner starts on that attempt, by design rather
than by defect. The alternative was the cancelling deadline ADR-0228 §14 defers,
and taking it here would have meant deciding what a half-composed plan is (§14).

**An attempt whose allowance is spent still plans once per turn**, so an owner who keeps asking
about one goal keeps getting answers and stops getting investigation. The degradation is to the
system as it stood before ADR-0228 — one plan per turn — and the composing flag is what makes it
legible rather than silent.

**`empty_reads` disappears from `Planner.plan`,** so every implementation and every fake must
move in one lane. That cost is stated rather than avoided, and §16 is why it is one lane.

## Alternatives considered

**Keep ADR-0228 §2(e) and raise only the count.** Rejected: with (e) intact a refused, failed,
expired or fully-deduplicated read ends the attempt's investigation at the first one, so a bound
of four would be unreachable on exactly the turns it exists for, and #2169's *"An inaccessible
source produces a justified alternative"* would still be impossible. Raising a bound whose
binding constraint is a different clause changes nothing.

**Keep `empty_reads` and add a second parameter for the other outcomes.** Rejected in §3: two
carriers for one ask, with two spellings of its state, and the first implementation to disagree
with itself is right in one of them.

**Make `ReadOutcome` carry the source vocabulary's own member rather than one of seven.**
Rejected: `SearchDisposition` alone has seventeen members and its docstrings name grounds — a
composer's refusal, a policy ruling, an attestation failure — that ADR-0242 §9's bar keeps away
from a rendered surface, and a planner is a rendered surface. Seven classes carry every
distinction the planner can act on and none it cannot.

**Put the allowance figures on `AttemptEffort` as declared limits beside the consumed
figures.** Rejected in §5: a `core` model field is *"a figure a caller can contradict"*, which
is the construction ADR-0228 §4 refuses by name for `LearningLoop.respond`. The record would be
more self-describing and the figures would be configurable by anyone who could construct the
model, and the second is worse than the first is good. The kind — a member of a closed
enumeration whose allowance an ADR ruled — buys most of the self-description at none of the
cost.

**Re-key ADR-0228 §4's PT20S on the attempt, as the design direction proposed.** Rejected in
§5: an attempt spans turns under ADR-0250 §12, so the figure would be checked against a quantity
that already holds earlier turns and would fire on turn 2 of every real conversation. Two
quantities, two gates, both kept.

**Give the reserve to composing as its own budget rather than as an unreachable share.**
Rejected in §6: a budget composing could exhaust is a second place for a turn to end with
nothing to show, which defeats what the reserve is declared for.

**Declare a per-attempt spend allowance.** Rejected in §8: ADR-0194 §7 derives the total,
ADR-0194 §1 puts the ceiling in `Settings` where a deployment decides it and *"unset means no
ceiling"*, and this decision has no measurement to set a code-fixed money figure from.

**Reintroduce a per-conversation search cap alongside the expansion.** Rejected in §11: the
expansion does not falsify the sentence ADR-0247 §5 rests on, a per-conversation cap binds on
the wrong unit, and the standing rule of 2026-09-12 forbids a user-facing restriction bought for
convenience alone.

**Write `GoalStatus.BLOCKED` on exhaustion.** Rejected in §9: it asserts the objective
unreachable on the evidence that the system stopped looking, which is ADR-0249 §4's own
circularity read from the other end.

**Write `GoalStatus.BLOCKED` where a source was unavailable and no read admitted a record.**
Rejected in §9, and it is the producer an earlier draft of this decision carried. It fails the
necessity limb: a request to summarise a note already in the assembled supply, accompanied by an
unnecessary `WEB_SEARCH` on a deployment with no account, meets that predicate exactly and then
answers correctly. One route being shut is not evidence the route was needed, and a status member
meaning *"this objective cannot currently be achieved"* is not the place to record that a search
did not run.

**Name a closed blocker vocabulary here.** Rejected in §9: the conditions are A6's, A8's and
A9's, and a vocabulary ratified with no producer is the empty box ADR-0249 §10 refuses to mint.

**Persist the unproductive-run count across turns.** Rejected in §7: it is a claim about an
ephemeral supply (ADR-0052 §3), and a user act between two rounds is new information that
honestly breaks a run.

**Let the planner-call allowance be the only stop.** Rejected in §7: four model calls on an
attempt that learned nothing after the first is precisely the *"repeated unproductive work"*
#2170 asks be detected, and the audit would record it as a bound reached rather than as waste.
