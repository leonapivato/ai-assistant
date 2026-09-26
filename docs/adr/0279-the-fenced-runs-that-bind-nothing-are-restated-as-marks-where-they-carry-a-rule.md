# 279. The fenced runs that bind nothing are restated as marks where they carry a rule

- Status: Accepted
- Date: 2026-09-26
- Authorization: on 2026-09-26 the owner answered "do your recommendations" to the
  dispatcher's recommendation on #2563, which was to write a new ADR restating the
  fenced rulings as its own marked clauses, because a ratified ADR cannot be edited.
  The dispatcher assigned the number 0279.
- **This ADR supersedes and amends no decision.** §§2 and 3 are stacked additions
  under ADR-0082 §1, and §5 classifies every ADR this touches. It writes one dated
  header note, on ADR-0197, because that ADR's own 2026-09-04 note states that nothing
  outside it closes the gap §2 closes.
- **It decides a `core/protocols.py` surface** — it makes binding the member sets and
  signatures of `RoutingRecorder`, `RoutingTrail` and two `AssistantEngine` members —
  so it owes both review lenses. It changes no Protocol, no `core` type, no code and
  no `PROTOCOL_VERSION`: every clause below describes what `main` already carries.

## Context

ADR-0089 §2:1 ends "A clause contains no fenced block", and ADR-0089 §2:3 rules that
"A line that fails any part of that grammar is not a mark, and no ADR is marked by
it." Four token-led block-quote runs carry a fenced block inside the quote (#2563):

| ADR | where | the run opens |
|---|---|---|
| ADR-0197 | §9 | `core/protocols.py` gains **two** Protocols on ADR-0185 §4's split |
| ADR-0217 | §7 | The owner's explicit act **after the fact** is two members |
| ADR-0245 | §5 | The whole of this decision rests on ADR-0238 §1's clause |
| ADR-0246 | §5 | The whole of this decision rests on ADR-0238 §1's clause |

A scan of every ADR at `d2c25133`, tracking fence state as ADR-0089 §2 describes,
finds these four and no others.

All four ADRs carry well-formed marks elsewhere, so they are marked ADRs (ADR-0089
§4:1), and under ADR-0089 §3:1 what these runs alone state "never supplies an
obligation". ADR-0277's clause identifiers follow ADR-0089 §2 and give the runs no
ordinal, so the identifiers after them are already fixed and this ADR moves none.

ADR-0089 §5:2 forbids adding a mark to a ratified ADR, "by a dated note or
otherwise". What remains is for a later ADR to state the rule as its own marked
clause. This is that ADR.

### What each run carries, read against the tree at `d2c25133`

**ADR-0197 §9.** In force: its only supersession, by ADR-0201, reaches §5. ADR-0197's
own dated note of 2026-09-04 already names what the run alone carried: "the signatures
as displayed, the **exactly four members and no others** of `RoutingTrail`, `recent`'s
newest-recorded-first ordering, its local `[1, 2**63)` refusal, and `export`'s
ADR-0085 §8c bound". The note says this gap is "a later decision's". The rest of the
run (the split, `record`'s single critical section, whole-record idempotence, `clear`)
is reachable from ADR-0197's marked clauses and §12's suite clauses, but only piece by
piece. `core/protocols.py` carries both Protocols with exactly the displayed members,
and `tests/permissions/routing_contract.py` pins the ordering and the refused limit.

**ADR-0217 §7.** In force: ADR-0276's supersession reaches §2 alone. This run is wider
than #2563's table suggests. Its fence is followed by a bare `>` and then a second
token line with no blank line between, so under ADR-0089 §2:1 the run continues
through the paragraph beginning "An act writes **only where §3's precedence lets it
win**". Both paragraphs are one non-mark: the two members with their signatures, and
the rule saying when an act writes and what it writes. ADR-0217 §7:9, the clause
right after the run, opens "The two consequences of that clause", so it relies on a
clause that binds nothing. `AssistantEngine.guard` and `AssistantEngine.unguard`
exist in `core/protocols.py` with the displayed signatures, and the engine's
implementation writes exactly as the run says.

**ADR-0245 §5 and ADR-0246 §5.** Each run names the ground the decision rests on,
ADR-0238 §1's rule that only a recorded act of the user sets a destination's trust,
and shows that rule in a fence. §4 below explains why neither is restated.

## Decision

### 1. What this ADR restates, and how

Each rule below is written as this ADR's own marked clause, one obligation per clause
(ADR-0089 §2:4). No clause holds a fenced block. Signatures are written as inline
code inside the clause, so each clause carries its whole obligation and does not
depend on a display in the prose beside it (ADR-0089 §3:2). No clause is broader than
the run it restates. Where a run can be read two ways, the clause says which reading
it takes and why.

### 2. The routing trail's two Protocols (ADR-0197 §9)

> **Normative.** `core/protocols.py` carries two Protocols for the routing trail of
> ADR-0197 §9, split by capability on ADR-0185 §4's pattern. `RoutingRecorder` writes
> and can answer nothing. Its member is `record`, with exactly the signature
> `async def record(self, record: RoutedOperationRecord) -> None`.

> **Normative.** `RoutingTrail` records and reads, and has exactly four members and no
> others, with exactly these signatures:
> `async def record(self, record: RoutedOperationRecord) -> None`,
> `async def recent(self, *, limit: int) -> tuple[RoutedOperationRecord, ...]`,
> `async def export(self) -> tuple[RoutedOperationRecord, ...]` and
> `async def clear(self) -> None`.

> **Normative.** `record` is specified once and binds both Protocols, because one
> concrete store satisfies both. It appends one row, returns nothing, and takes the
> identity the caller minted instead of producing one.

> **Normative.** `record`'s checks and its append are one critical section: the row-`id`
> equality test, the `route_id` test, the append and ADR-0197 §9's pruning run under
> one transaction or one lock. Two concurrent `record` calls carrying a colliding
> `route_id` therefore cannot both observe no conflict and both append. Exactly one
> succeeds, the other raises `RoutingTrailError`, and the losing call's act does not
> proceed.

> **Normative.** `record` is idempotent over the whole frozen record and never over
> the `id` alone. If a row with the same `id` is already present and every field equals
> the one supplied, nothing is appended and no error is raised. If a row with the same
> `id` is present and any field differs, `record` raises `RoutingTrailError`, appends
> nothing, and the act that row precedes does not proceed.

> **Normative.** `RoutingTrail.recent` answers newest-recorded first. It refuses a
> `limit` outside `[1, 2**63)` locally, before any I/O, as ADR-0186 §3 requires of
> every bounded listing.

> **Normative.** `RoutingTrail.export` answers every row the trail holds, in recording
> order with the oldest-recorded row first, and is bounded only by ADR-0085 §8c's
> payload limit.

> **Normative.** `RoutingTrail.clear` destroys every row, for ADR-0007's deletion
> right.

**`export`'s order is a reading, and this is the ground for it.** The run says
`export` "answers the whole trail in the same order". The nearest order in the same
sentence is `recent`'s newest-recorded first, so the phrase can be read that way. It
is read here as recording order, for three reasons. First, the run puts `RoutingTrail`
"on ADR-0185 §12's shape", and in that shape `SourceReadTrail.export` returns "every
record the store holds, in recording order". `recent` is the newest-first page drawn
from that order. Second, ADR-0197's implementing lane (PR #1634), reviewed under both
lenses, read the run this way. The `RoutingTrail.export` docstring says "every row the
store holds, in recording order", and the shared suite's
`test_export_returns_rows_in_recording_order` pins `r-0, r-1, r-2` against every
implementation. Third, reading it the other way would make a clause that `main`
breaks on the day it binds. A restatement exists to make the ruling bind, not to
decide something new in the process.

### 3. The owner's two acts after the fact (ADR-0217 §7)

> **Normative.** The owner's explicit act after the fact is two members of the
> `AssistantEngine` Protocol in `core/protocols.py`, with exactly these signatures:
> `async def guard(self, record_id: Identifier) -> Placement | None` and
> `async def unguard(self, record_id: Identifier) -> Placement | None`.

> **Normative.** `guard` and `unguard` write only where ADR-0217 §3's precedence lets
> the act win, and only where what the act would write differs from what the record
> carries. An act whose whole effect would be to rewrite a placement without changing
> its reach or its setter writes nothing.

> **Normative.** Where `guard` writes, it writes reach `OWNER` with setter `OWNER_ACT`
> and the instant of the act. Where `unguard` writes, it writes reach `ANYONE` with
> setter `OWNER_ACT` and the instant of the act.

> **Normative.** Where a record's placement has setter `DERIVED`, `unguard` writes
> nothing. An act does not lift the limit ADR-0217 §3:13 sets on the owner's act.

> **Normative.** An `OWNER_ACT` stamp is written only by the owner's acts that
> ADR-0217 §7 names: `guard`, `unguard`, and the `guarded` flag honoured at write under
> ADR-0217 §7:1. Nothing else writes one.

**The last clause states which reading of "Nothing else" it takes.** In the run,
"Nothing else writes an `OWNER_ACT` stamp" closes the paragraph about `guard` and `unguard`. Read
literally in that paragraph, it would forbid the write-time flag that ADR-0217 §7:1
rules "is written with reach `OWNER` and setter `OWNER_ACT`", which is one of §7's own
acts under its heading "The acts: one flag at write, two operations after the fact".
So the clause names all three acts. It says nothing new about a fold. ADR-0217 §3
already decides what setter a fold's survivor carries, and ADR-0217 §1:7 decides that
propagation mints no instant.

With §3's first clause, ADR-0217 §7:9 ("The two consequences of that clause") and
ADR-0217 §7:11 ("The two members are **`AssistantEngine`'s and no other
Protocol's**") now point back to a clause that binds.

### 4. ADR-0245 §5 and ADR-0246 §5 are not restated

Neither run states an obligation that is not already bound somewhere else, so neither
is restated.

- **What the runs say is not normative under ADR-0089 §1:1.** "The whole of this
  decision rests on ADR-0238 §1's clause" names a ground and constrains no one. "This
  ADR quotes it, changes no word of it, and relies on it entire" (ADR-0245), and
  "ADR-0245 §5 binds entire, quoted rather than restated" (ADR-0246), classify the
  change being made. ADR-0089 §1:1 names "a classification of the change being made" as
  not normative.
- **The obligation the ground carries is already marked.** Each ADR's next clause,
  ADR-0245 §5:1 and ADR-0246 §5:1, is well-formed: "Any later loosening of that clause
  reopens this decision", and the loosening ADR "states in its own text what becomes of
  this decision". The runs identify what "that clause" means, and ADR-0089 §3:1 lets
  unmarked text do exactly that.
- **The quotation is another ADR's rule, and that rule has moved.** The fenced text is
  ADR-0238 §1's own clause. It binds in ADR-0238 as that ADR's records leave it, and
  ADR-0247 and ADR-0260 have since partially superseded it for a request at a
  configured provider. Restating it here would put a second statement of another ADR's
  rule into the marked set (ADR-0277 §3's second rule forbids quoting a marked clause
  with the token). It would also misstate the corpus, because "relies on it entire" no
  longer holds. ADR-0247, the loosening, has already answered both reopen clauses: it
  records that ADR-0246 §1's rule "binds entire", and it lists ADR-0245 among the ADRs
  on which no record is owed.

### 5. This ADR classified under ADR-0070 §1 and ADR-0082 §1

- **ADR-0197 and ADR-0217: stacked additions.** Every clause of §§2 and 3 makes
  binding what a run of those ADRs states, with the meaning it states. No sentence of
  either Decision becomes false or broader, and a reader holding only that ADR's marked
  clauses builds what they built before. So no `Status` edit is owed on either, and no
  record is owed on ADR-0217.
- **Why not a partial supersession.** ADR-0089 §5's prose describes the route for an
  old rule as a restatement that "partially supersede[s] the earlier one for that
  scope". That fits a rule in an unmarked ADR, which still binds as prose and would
  otherwise be stated twice. Here the earlier text binds nothing (ADR-0089 §3:1), so
  no binding statement is replaced, and ADR-0070 §1's test finds nothing to supersede.
- **ADR-0197's header note: one record.** Its 2026-09-04 note says that the members,
  the order, the limit domain and the bound the run carries have no binding statement,
  and that "nothing outside this ADR closes that either". That sentence stops being
  true when §2 binds. A reader holding only ADR-0197 would treat the gap as open, so
  ADR-0082 §1's test comes out *yes* for that note. The record is a dated note alone
  (ADR-0082 §2: the `Status` line leads with `Partially superseded by`), and under
  ADR-0277 §3 it says nothing about this ADR's status beyond when the change takes
  effect.
- **ADR-0245 and ADR-0246: nothing owed.** §4 restates nothing of either.
- **ADR-0089: applied, not changed.** §2's grammar, §3's reading and §5's forward-only
  rule bind as written. This ADR adds no mark to a ratified ADR and re-marks no line.
- **ADR-0277: applied, not changed.** No clause identifier in any of the four ADRs
  moves, and the runs keep having no ordinal.

## Consequences

- The members, signatures, order, limit domain and bound of the routing trail's two
  Protocols bind, and so do the signatures of `guard` and `unguard` and the rule for
  when they write. Each has a clause identifier: `ADR-0279 §2:1-8` and
  `ADR-0279 §3:1-5`.
- Nothing is built. `main` already does what every clause says. A lane that finds the
  tree disagrees with one has found a defect in the tree.
- A reader of ADR-0217 §7 still finds the signatures in a fence there that binds
  nothing, and no note on ADR-0217 points here. That is ADR-0082 §1's stacked-addition
  rule, and the cost is the same as for every stacked addition: the rule is found in
  the ADR that makes it.
- Whether anything reports a fence inside a token-led run is still ADR-0089 §7's
  open question (#2038). This ADR does not decide it.
- Revisit if another token-led run holding a fence is found. The scan in Context found
  none beyond these four, and one ratified later would need a restatement of its own;
  this ADR covers only the four #2563 names.
