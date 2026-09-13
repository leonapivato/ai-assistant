# 258. The investigation's per-ask outcome is named ReadAskOutcome, and the permission trail keeps ReadOutcome

- Status: Proposed
- **Partially supersedes**
  [ADR-0251](0251-an-attempt-investigates-in-bounded-rounds-over-typed-read-outcomes-and-keeps-a-reserve-to-answer-with.md)
  — **one scope, and it is a name: `ReadOutcome` → `ReadAskOutcome`, wherever ADR-0251 writes it
  for the model §3 mints.** That is §3's minting clause, *"`core/types.py` gains
  **`ReadOutcome`**, a frozen model with `extra="forbid"` carrying exactly two fields"*, and its
  parameter clause, *"**`read_outcomes: Sequence[ReadOutcome] = ()`**"* — **and six further
  sites outside §3**, two of them marked: **§12's writer clause** (*"each round's
  `ReadOutcomeKind` and the `ReadOutcome` carrying it"*) and **§16's L1 clause** (*"`core/types.py`
  gains `ReadOutcomeKind`, `ReadOutcome` and `AttemptKind`"*), plus §15's working for ADR-0240 §7,
  the header bullet stating that same scope, §17's arm 2 and the Alternatives entry. §1 states the
  rule and enumerates every site. The model is named **`ReadAskOutcome`** and the annotation is
  `Sequence[ReadAskOutcome]`, because `core/types.py` has held
  `ReadOutcome` since
  [ADR-0185](0185-every-attempt-to-read-a-source-is-recorded-refusals-included-and-the-trails-bound-has-no-unlimited-spelling.md)
  §1 for the permission trail's own record of how a gated source read ended. **Every other
  clause of §3 binds verbatim** — the two fields `ask` and `outcome` and their types, the
  `extra="forbid"`, the carries-nothing-else clause, the parameter's name, its default, its
  keyword position and its additive-in-shape character, the breaking-change flag, the
  one-entry-per-serviced-ask-in-servicing-order clause and its `()` reading, the
  nothing-the-source-said clause, the ask-carried-back-unaltered clause, the
  carrier-and-audit-governed-separately clause, the mints-nothing-durable clause and the planner-is-not-told-which-round clause — and
  **no clause anywhere in ADR-0251 loses an obligation or gains one** — §§1-2 and §§4-18 keep
  every ruling they carry, and the two marked clauses named above are replaced in the model's
  name and in nothing else. One identifier moves, this ADR imposes nothing beside it, and §6
  shows the working.
- **No other ADR is superseded in whole or in part**, and §5 shows the working for each one a
  reader would expect to be — ADR-0185, ADR-0240, ADR-0249 and ADR-0015. **ADR-0185 is the one
  to check first**: its §1 `ReadOutcome` is the whole reason this decision exists, and it is untouched
  in name, in members and in every reader of it.
- **Decides the name of a type in `src/ai_assistant/core/types.py` and the annotation on
  `src/ai_assistant/core/protocols.py`'s `Planner.plan`.** **It is a BREAKING contract change
  under golden rule 5** and is flagged as one: an implementation following ADR-0251 §3 as
  ratified writes a different symbol and a different annotation than one following this. It is
  therefore a **contract-surface decision** and takes **both** review lenses, which
  `CONTRIBUTING.md` requires of *"the ADR deciding that surface"* however prose-only its PR.
  ADR-0251 §3's own BREAKING flag on the parameter replacement binds verbatim beside it (§2).
  **No implementation has to move for the break**, because the tree already carries the name
  this ADR rules — which is itself irregular, and §4 owns it.
- Date: 2026-09-13

## Context

### Where this comes from

Issue #2281, filed from PR #2280 while ADR-0252 was being written against `origin/main`
`54c6b72e`. ADR-0251 §3 mints a frozen model named `ReadOutcome` in `core/types.py`. That
file has held a `ReadOutcome` since ADR-0185 §1 — a `StrEnum` over how one **gated source
read** ended, carried on `SourceReadRecord` and read by the audit path — so §3's clause could
not be implemented as written without shadowing or overloading it. ADR-0251's L1 lane
(PR #2287) landed the model as **`ReadAskOutcome`** and `Planner.plan`'s replaced parameter as
`read_outcomes: Sequence[ReadAskOutcome] = ()`, recorded the choice in the type's own
docstring, and pinned the hazard in a test.

PR #2315 then took #2281 as a header record — a dated note on ADR-0251 saying the
implementation had renamed the model. **Both review lenses blocked that note on round 1,
independently and on the same reading**, and the finding was right. §3's type name and its
`Planner.plan` annotation are a `core` contract surface: a reader holding ratified §3 writes a
different symbol into `core/types.py` and a different annotation onto the Protocol than a
reader holding the note. Under ADR-0070 §1 — *"A change to what was decided is anything a
reader would act on differently"* — that is a change to what was decided and not an amendment,
so only a superseding ADR can make it, reviewed while `Proposed` and merged on its own
(golden rule 5, ADR-0015 §5). PR #2315 instead left a note that **records the divergence and
decides nothing**, states that §3 binds as ratified, directs a reader to neither name, and says
the reconciliation is owed. **This ADR is that reconciliation.**

**PR #2315 merged ahead of this lane**, so its note of 2026-09-13 is on ADR-0251 at this ADR's
base (`origin/main` `f3bd08f5`) and this change adds a second note directly below it. The two are
compatible and deliberately so: that note records the divergence and says the reconciliation is
owed, and this one is the reconciliation. Its text is left unrewritten, which is what the
append-only mechanism requires (ADR-0070 §1).

### The tree, read rather than assumed, at `origin/main` `f3bd08f5`

Three types, one file, and not one of them is a draft:

```python
class ReadOutcomeKind(StrEnum):
    """What became of one serviced ask, as the planner is told it (ADR-0251 §2)."""


class ReadAskOutcome(BaseModel):
    """One ask this turn serviced, and what became of it (ADR-0251 §3)."""


class ReadOutcome(StrEnum):
    """How one attempt to read a source ended (ADR-0185 §1)."""
```

`core/protocols.py`'s `Planner.plan` carries `read_outcomes: Sequence[ReadAskOutcome] = (),`.
`ReadAskOutcome`'s own docstring states the divergence rather than hiding it — *"**The name is
this lane's and the ADR's is** ``ReadOutcome`` (issue #2281)"* — and
`tests/core/test_read_outcome_types.py::test_it_is_a_different_type_from_the_gated_reads_outcome`
pins what the collision leaves behind: both vocabularies are `StrEnum`s and their value sets
intersect in exactly `{"refused", "failed"}`, so `ReadOutcomeKind.REFUSED ==
ReadOutcome.REFUSED` is `True` at run time and a `set` membership test cannot tell them apart.
That is the strongest available argument for keeping the two spelled differently, and it is
already on the tree as an assertion rather than as prose.

### Why they are different facts about different things

A **gated read's** `REFUSED` says the first `SourceGrants.live` check answered `None`, so the
source "is not resolved, not opened and not parsed" (ADR-0097 §5, ADR-0185 §1). An **ask's**
`REFUSED` says *"the source **decided** not to answer, on a ground it owns"* (ADR-0251 §2). ADR-0185 §1's enum is the permission trail's record, durable on `SourceReadRecord` and read
by an operator; ADR-0251 §3's model is an in-process argument built from one turn's servicings
and discarded with the turn, minting nothing durable by its own clause. Neither is derivable
from the other. One name cannot carry both, and no reading of either ADR asks it to.

### What this ADR is not allowed to settle

- **Whether the two vocabularies should ever be reconciled, merged or ordered.** They are
  different facts (above) and this decision keeps them apart; anything further is a decision of
  its own.
- **Anything of ADR-0251 but one identifier.** The name is written nine times across §3, §12,
  §15, §16, §17, the header bullet and the Alternatives (§1 counts and lists them); at every one
  of them the name is the only thing replaced, and no other clause of any section moves.
- **Anything of ADR-0185.** §5 shows why no record is owed there.
- **Whether ADR-0015 §5's ordering should change.** §4 records that it was breached and that the
  breach is not cured by the record. ADR-0015 is untouched by this ADR and nothing here is a
  precedent; a governance decision about remediation, if one is wanted, is its own ADR.
- **Whether an implementation may conflate the two vocabularies.** They overlap on two string
  values and nothing today stops the conversion; §3 names that, files it as #2320 and rules
  nothing about it. A guard is code, and the clause that would demand one is a decision this lane
  is not fenced for.

## Decision

### 1. The model ADR-0251 §3 mints is named `ReadAskOutcome`

> **Normative.** The frozen model ADR-0251 §3 mints in `core/types.py` is named
> **`ReadAskOutcome`**, and that is its name **wherever ADR-0251 names it** — in §3 and in every
> other clause, section and header bullet of that ADR that writes `ReadOutcome` for this model.
> A reader implementing, citing or auditing any of them writes and cites `ReadAskOutcome`.

> **Normative.** `core/protocols.py`'s `Planner.plan` parameter that ADR-0251 §3 replaces is
> annotated **`read_outcomes: Sequence[ReadAskOutcome] = ()`**. The parameter's name
> `read_outcomes`, its default `()`, its keyword position and its additive-in-shape character
> are ADR-0251 §3's and are not touched by this clause.

**The sites, so a reader can check the clause rather than trust it.** ADR-0251's ratified text
writes `ReadOutcome` for this model **nine times**: three in §3, and **six at six further sites
outside it**. The clause above reaches all nine. Two of the six are **marked**, which is why the
scope could not stop at §3 — two marked clauses reading `ReadOutcome` beside a supersession
reading `ReadAskOutcome` would leave the ADR instructing an implementation two ways at once:

- **§3's minting clause and its parameter clause**, and the heading above them.
- **§12's writer clause** (marked) — *"each round's `ReadOutcomeKind` and the `ReadOutcome`
  carrying it"*, in the enumeration of what `orchestration` mints and no model output sets.
- **§16's L1 clause** (marked) — *"`core/types.py` gains `ReadOutcomeKind`, `ReadOutcome` and
  `AttemptKind`"*, in the lane cut.
- **§15's working for ADR-0240 §7** and **the header bullet stating that same scope**, each
  writing the annotation `Sequence[ReadOutcome]`.
- **§17's arm 2** — *"rather than from a constructed `ReadOutcome`"*.
- **The Alternatives entry** — *"Make `ReadOutcome` carry the source vocabulary's own member
  rather than one of seven"*.

**Two further occurrences are deliberately not reached**, and they are not an oversight in the
count above: PR #2315's appended dated note of 2026-09-13 quotes §3's minting clause and names
ADR-0185 §1's enum. It is an appended note rather than ratified decision text, it directs a
reader to neither name by its own terms, and under ADR-0070 §1 an appended note is never
rewritten. The note this change adds directly below it is what supersedes what it records.

Nothing else of any of them moves: §12's writer clause still says `orchestration` mints every
value and no model output sets one; §16 still cuts two lanes in that order; §15's working for
ADR-0240 §7 still supersedes exactly the parameter declaration; §17's arm still asks for a real
source vocabulary value; the Alternative is still rejected on the ground it states.

### 2. Every other clause of ADR-0251 §3 binds verbatim, over the renamed model

> **Normative.** Every clause of ADR-0251 §3 other than the model's name binds **verbatim** and
> is read over `ReadAskOutcome`: the two fields `ask` and `outcome` and their types, the
> `extra="forbid"`, the carries-nothing-else clause, the parameter's name, default, keyword
> position and additive-in-shape character, the breaking-change flag it carries, the
> one-entry-per-serviced-ask-in-servicing-order clause together with its reading of `()`, the
> nothing-the-source-said clause, the ask-carried-back-unaltered clause, the
> carrier-and-audit-governed-separately clause, the mints-nothing-durable clause and the
> planner-is-not-told-which-round clause. This decision replaces an identifier and nothing
> else.

> **Normative.** Every clause of ADR-0251 outside §3 that this decision reaches — §12's writer
> clause, §16's L1 clause, §15's working for ADR-0240 §7 and the header bullet stating it, §17's
> arm 2 and the Alternatives entry — binds **verbatim** but for the model's name. No obligation
> of any of them is lifted, narrowed or widened, and §§1-2 and §§4-18 otherwise stand entire.

> **Normative.** ADR-0251 §2's `ReadOutcomeKind` keeps its name, its seven members and their
> values and meanings. Nothing in this decision reaches it, and the `outcome` field's type is
> `ReadOutcomeKind` exactly as §3 states.

### 3. Why the name was taken, and what this ADR deliberately does not decide about it

**This section is unmarked and binds nothing** (ADR-0089 §3). It is the ground for §1's choice
of identifier, not a second decision riding beside it, and it is unmarked on purpose: §§1-2
change one identifier, and an ADR whose header says so may not quietly add an obligation four
lines lower.

**The ground.** `core/types.py` has held ADR-0185 §1's `ReadOutcome` since 2026-08-23 — the
`StrEnum` over how one gated source read ended — and nothing in this ADR reaches it. It keeps
its name, its six members and their meanings for the ordinary reason that no decision has
superseded it, and §5 shows that none is owed. The Context above says why the two cannot share
one name: they are different facts about different acts, one durable on `SourceReadRecord` and
rendered to an operator, the other an in-process argument discarded with its turn. That is why
§1 moves the newer name and not the older one, and the Alternatives section takes the other
option seriously before rejecting it.

**What this ADR does not decide, and why it declines to.** The two vocabularies' values
intersect in `refused` and `failed`, so an implementation *can* conflate them — pydantic
validates a `StrEnum` by value, and `ReadAskOutcome(ask=…, outcome=ReadOutcome.REFUSED)` is
accepted today and silently becomes `ReadOutcomeKind.REFUSED`. **That is a real defect and it is
filed as #2320**, not ruled here. An earlier draft of this section marked a clause forbidding the
conversion; both review lenses were right to block it. A prohibition no code enforces is worth
less than the validator and the regression arm #2320 asks for, the enforcement is `src/` and
`tests/` work this docs-only lane is not fenced for, and imposing a new obligation would have
made this ADR's own header false. Whoever takes #2320 may want a clause; that clause is theirs to
propose.

### 4. The implementation preceded this decision, and this ADR records that rather than curing it

> **Normative.** This decision authorises no implementation work and no further contract
> change. The name it rules is already on the tree — `ReadAskOutcome` in `core/types.py` and
> `read_outcomes: Sequence[ReadAskOutcome] = ()` on `Planner.plan` — so the change that ratifies
> this ADR alters no file under `src/`, and no lane cites this ADR as ground for one.

**What happened, stated plainly.** ADR-0251 was ratified and merged as its own PR before its
implementation, exactly as golden rule 5 and ADR-0015 §5 require of a substantive contract ADR.
Its §3 then turned out to be unimplementable as written, and the L1 lane could not both implement
§3's clause and leave ADR-0185 §1's ratified, wire-visible, operator-rendered enum standing. It
chose the second, spelled the new model in full, and filed #2281. So since PR #2287 merged, the
*identifier* on the tree has run ahead of the decision that rules it, and this ADR is that
decision.

**ADR-0015 §5's ordering was breached, and this ADR claims no exemption from it.** §5 requires a
substantive contract ADR to ship *"as its own PR, ratified before the implementation PR that
depends on it"*. An earlier draft of this section read §5's parenthetical — *"Trivial ADRs
(amendments, status changes, supersessions) are exempt"* — as covering this document. **Both
review lenses rejected that reading and they were right.** `CONTRIBUTING.md` fixes what the
parenthetical means: the trivial edits are *"an in-place amendment, the `Proposed` → `Accepted`
ratification flip, or recording on an ADR's status that a superseding ADR has landed"*, and the
exemption *"does not lift any review the ADR's substance requires"*. It is the ADR-0251 `Status`
edit that is trivial, not the decision making it. So this is a substantive contract ADR whose
implementation landed first, it takes both lenses for that reason, and the ordering §5 fixes was
breached — by PR #2287, merged 2026-09-12, the day before this document was written.

**What §5 does not supply is a remedy for a breach that has already merged.** It states an
ordering, not a repair. ADR-0070 §1 states the corpus's only mechanism for a ratified clause and
the world disagreeing — *"Any change to what was decided requires a new ADR that supersedes the
old one"* — and this is that ADR, written for that reason. The repository owner ruled the same
disposition on #2281 before this lane opened, naming what it is owed clause by clause: *"one ADR,
partially superseding **ADR-0251 §3** in the model's name alone"*. Review is advisory on exactly
this point — `CONTRIBUTING.md`: *"the author still owns ratification; the reviewer only surfaces
blind spots"* — and what the reviewer surfaced here is recorded above rather than argued away.

**Why that is recorded here and not quietly fixed.** The order ADR-0015 §5 fixes exists so that
nothing implements against an unreviewed contract, and the exposure here is real but bounded:
what went unreviewed was one identifier, chosen to avoid a collision the ADR's author did not
see, disclosed in the type's docstring, in a test and on an open issue from the day it landed.
The alternative available to that lane was to implement §3 literally and shadow ADR-0185 §1 —
which is the outcome ADR-0015 §5 exists to prevent, reached by obeying it. Recording the
irregularity is the remedy that is actually available once the code has merged; pretending the
decision came first is not.

**Unwinding is not the remedy, and no text asks for it.** The other direction available on
paper — revert `ReadAskOutcome` from `main`, merge this ADR, re-land the identical code — would
revert a contract that has shipped (ADR-0251 §16 moved `PROTOCOL_VERSION` **from 38 to 39** on
it, and `wire/envelope.py` records 39 as ADR-0251's), across
`core`, `orchestration`, `wire`, the CLI and the fakes, to arrive at a tree byte-identical to the
one that exists. It buys no review that this ADR does not buy: what was never reviewed is one
identifier, and it is what §1 reviews. ADR-0015 §5 does not require it, ADR-0070 does not
contemplate it, and it is far outside a docs-only lane's fence. The append-only corpus's answer
to "the record and the world disagree" is to move the record, which is what this is.

**And it licenses nothing.** ADR-0015 §5 is untouched by this ADR (§5), and nothing here is a
precedent for landing a contract surface no ADR has ruled. What PR #2287 did *right* is the part
worth copying: it did not improvise silently. It made the minimal choice the collision left open,
spelled the divergence out in the type's own docstring, pinned the hazard in a test, and filed
#2281 the same day — so the gap was visible, bounded and closable, which is why it could be
closed by this ADR rather than discovered later. What it could have done instead is stop and ask
before landing the contract, and a lane that meets the same wall should prefer that; the record
here is the remedy for having gone the other way, not an endorsement of it.

### 5. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's, applied to the earlier ADR's text: would a reader holding
only that ADR now act differently, or read one of its clauses more widely than it now holds?

- **ADR-0251 — a record is owed, and it is a partial supersession.** A reader holding §3 writes
  `ReadOutcome` into `core/types.py` and `Sequence[ReadOutcome]` onto `Planner.plan`; a reader
  holding §12 mints a `ReadOutcome` per round; a reader holding §16 adds one to `core/types.py`;
  a reader holding this ADR writes `ReadAskOutcome` at every one of them. That is acting
  differently on the decision itself, so under ADR-0070 §1 it is a supersession and not an
  amendment, and it is **partial** — one identifier across the nine occurrences §1 counts, and
  nothing else (§3 of ADR-0070 makes the partial form first-class). ADR-0251's `Status` takes the leading
  `Partially superseded by` token with the scope naming exactly what was replaced (ADR-0070
  §4), and the record itself lives in the appended dated note this change adds (ADR-0082 §2,
  ADR-0070 §1). **It is the second note ADR-0251 carries**: PR #2315's note of 2026-09-13 —
  which records the divergence and decides nothing — merged ahead of this lane and stands
  directly above it, unrewritten. This note decides what that one could only record, and says
  so in its first sentence. No earlier note is edited, which is what the append-only mechanism
  requires (ADR-0070 §1).
- **ADR-0185 — nothing is recorded, and nothing is owed.** No clause of ADR-0185 §1 becomes
  false or over-wide. Its enum keeps its name, its six members, its totality claim, its
  `SourceReadRecord` home and every consumer rule §1 states about it; a reader holding ADR-0185
  alone acts identically before and after. **This ADR adds no obligation about it either**: §3
  is unmarked, so under ADR-0089 §3 it supplies none, and the six marked clauses are §§1-2's
  five about ADR-0251's naming of the model and §4's one about this ADR's own scope. ADR-0082 §1 is explicit that
  a record may not be demanded on book-keeping grounds where no clause of the earlier ADR fails
  ADR-0070 §1's test, and none does.
- **ADR-0240 — nothing is recorded.** §7's `empty_reads: Sequence[ReadAsk] = ()` was already
  replaced by ADR-0251 §3, and ADR-0251's own header carries that record. This ADR renames the
  replacement, not the clause ADR-0240 wrote, so no sentence of ADR-0240 changes its truth value
  by this decision. Its clauses that ADR-0251 §3 restates verbatim — nothing the source said,
  the ask never edited, the separate governance — bind over `ReadAskOutcome` by §2 above.
- **ADR-0249 — nothing is recorded.** §7's parameter-preservation clause was already partially
  superseded by ADR-0251 in the `empty_reads` term alone, and ADR-0249's header carries that.
  The parameter's *name* is unchanged here, so nothing further reaches it.
- **ADR-0015 — nothing is recorded.** §4's account of the order the implementation actually took
  is a statement of fact about this project's history, not a change to §5's rule, and no reader
  of ADR-0015 acts differently for it.

### 6. This ADR classified under ADR-0070 §1 and ADR-0082 §1, edit by edit

Two files change, and both edits are the permitted shapes:

- **This new file.** A new ADR is not an edit to a ratified one.
- **ADR-0251's `Status` line**, `Accepted` → `Partially superseded by ADR-0258 (<scope>)`.
  ADR-0070 §1 permits "recording a supersession that has landed" as an in-place header edit, and
  presupposes the superseding ADR exists — it does, it is this file, and the edit lands in the
  same PR that ratifies it. The line is one physical line, the leading token leads,
  `Accepted` is dropped, and the scope names a clause and carries no `ADR-NNNN` token, so
  ADR-0070 §4's extraction invariant holds (every `ADR-NNNN` after the leading token is a
  target).
- **ADR-0251's appended dated note.** ADR-0070 §1 requires it in every case and permits "adding
  a dated header note"; ADR-0082 §2 puts the record in the note where the line carries the
  leading token. ADR-0001's own header is the precedent for the form.

**No ratified decision text is rewritten anywhere.** ADR-0251's Context, Decision and
Consequences are byte-identical after this change, every header note it already carries is left
unedited, and no mark is added to any ratified ADR (ADR-0089 §5).

### 7. Marking, review and ratification

This ADR is **marked** (ADR-0089), and it carries **six** clauses: two in §1, three in §2 and one
in §4. Under ADR-0089 §3 those six are the whole of what it obligates — the prose beside them is
read to determine what they mean and supplies no obligation of its own. **§3 is unmarked on
purpose** (§3 says why), and §§5-6 are classification of this change, which ADR-0089 §1 puts
outside the normative set.

It decides the name of a type in `core/types.py` and the annotation on `core/protocols.py`'s
`Planner.plan`, so it **is** a contract-surface change and **both lenses are required**, not
elective: `CONTRIBUTING.md` → "Stop when the required reviews are green" says a change is
contract-surface *"when it touches `core/protocols.py` or `core/types.py` — **or when it is the
ADR deciding that surface**, even though such a PR is prose only"*, and `docs/review/guide.md`
says the same. This lane runs both on every round, on one committed tree. The ADR is reviewed
while it stands `Proposed` and ratified in this same PR by the isolated one-line `Proposed` →
`Accepted` flip ADR-0165 exempts from a fresh round; that flip is the trivial edit
`CONTRIBUTING.md` describes, and it lifts none of the review above it.

## Consequences

**What becomes easier.** A reader of ADR-0251 §3 and a reader of `core/types.py` now write the
same symbol, which has not been true since PR #2287 merged. #2281 closes. The debt PR #2315
recorded and could not discharge is discharged, and the two `refused`/`failed` vocabularies have
a ratified reason to stay apart rather than a lane's docstring.

**What becomes harder.** ADR-0251 §3 can no longer be quoted whole without its supersession —
the name in the ratified text is not the name to implement — which is the ordinary cost of a
partial supersession and is why ADR-0070 §4 requires the scope to be specific. A reader who
greps the corpus for `ReadOutcome` still finds §3's ratified sentences saying `ReadOutcome` about
the model; the `Status` line and the dated note are what point them here.

**Follow-on work.** #2320 is the substantive one: the two vocabularies overlap on `refused` and
`failed`, and `ReadAskOutcome.outcome` accepts ADR-0185 §1's member on those two values today.
This ADR names the hazard (§3) and rules nothing about it; the validator and its regression arm
are `src/` and `tests/` work.

Two docstrings on the tree say the name is "this lane's" and that the ADR's
is `ReadOutcome` — `ReadAskOutcome`'s own docstring in `core/types.py`, and the module header of
`tests/core/test_read_outcome_types.py`. Those sentences go stale the moment this ADR is
accepted, and correcting them is outside this docs-only change's fence; it is filed as its own
issue (#2319) rather than folded in.

**What would trigger revisiting this.** A decision that gives the two vocabularies one home, or
an ADR that retires ADR-0185 §1's enum, would make the collision this ADR routes around
disappear; §1 would then be the only thing naming the model, and a fresh decision could rename
it freely.

## Alternatives considered

**Rename ADR-0185 §1's enum instead, and give §3 the name it asked for. Rejected.** It is the
only other way to seat both types in one module, and it is worse on every count. ADR-0185 §1's
`ReadOutcome` is **ratified, implemented and wire-visible**: it is a field type on
`SourceReadRecord`, `wire/envelope.py` records that "``SourceReadRecord`` and ``ReadOutcome``
were promoted by ADR-0185", `interfaces/cli.py`'s `_read_ending` renders every member to an
operator, and its six members are asserted total over ADR-0097 §5 and ADR-0093 §8's outcomes. Renaming it would be a
breaking contract change touching a persisted record's type, owed its own migration reasoning,
in order to free a name for a model that is an in-process argument discarded with the turn. And
the collision was **the later ADR's to avoid**: ADR-0185 has held the name since 2026-08-23 and
ADR-0251 §3 minted over it without noticing, so the cost of the mistake belongs where the
mistake was made. The deciding argument is smallness — renaming the *newer*, non-durable,
non-wire-visible type is the change that moves the fewest readers, and it is the change the tree
already made.

**Leave §3 unimplementable and record the divergence only. Rejected, and already tried.** This
is what PR #2315 did after both lenses blocked the stronger note, and it was right *for that
lane's fence*: it left a reader directed to neither name and the reconciliation explicitly owed.
It is not a resting place. A ratified `core` contract clause that no implementation can obey,
with a note beside it saying so, is exactly the state ADR-0070 §1 provides the superseding form
to end.

**Give the model a name unrelated to either, so neither ADR's text goes stale. Rejected.** It
would cost a rename on the tree, on `Planner.plan`, and across every fake and test that names
the parameter's type, to buy nothing: §3's text goes stale on the model's name under any option
but literal shadowing, and `ReadAskOutcome` already says in one word what distinguishes it —
the outcome **of an ask**.
