# 258. The investigation's per-ask outcome is named ReadAskOutcome, and the permission trail keeps ReadOutcome

- Status: Proposed
- **Partially supersedes**
  [ADR-0251](0251-an-attempt-investigates-in-bounded-rounds-over-typed-read-outcomes-and-keeps-a-reserve-to-answer-with.md)
  — **one scope, and it is a name.** §3's minting clause in the model's name alone,
  *"`core/types.py` gains **`ReadOutcome`**, a frozen model with `extra="forbid"` carrying
  exactly two fields"*, and §3's parameter clause in the same term,
  *"**`read_outcomes: Sequence[ReadOutcome] = ()`**"*: the model is named **`ReadAskOutcome`**
  and the annotation is `Sequence[ReadAskOutcome]`, because `core/types.py` has held
  `ReadOutcome` since
  [ADR-0185](0185-every-attempt-to-read-a-source-is-recorded-refusals-included-and-the-trails-bound-has-no-unlimited-spelling.md)
  §1 for the permission trail's own record of how a gated source read ended. **Every other
  clause of §3 binds verbatim** — the two fields `ask` and `outcome` and their types, the
  `extra="forbid"`, the carries-nothing-else clause, the parameter's name, its default, its
  keyword position and its additive-in-shape character, the breaking-change flag, the
  one-entry-per-serviced-ask-in-servicing-order clause and its `()` reading, the
  nothing-the-source-said clause, the ask-never-edited clause, the separately-governed-audit
  clause, the mints-nothing-durable clause and the planner-is-not-told-which-round clause — and
  §§1-2 and §§4-18 are untouched. §3 loses no obligation and gains none; one identifier moves,
  and §6 shows the working.
- **No other ADR is superseded in whole or in part**, and §5 shows the working for the three a
  reader would check — ADR-0185, ADR-0240 and ADR-0249. **ADR-0185 is the one to check
  first**: its §1 `ReadOutcome` is the whole reason this decision exists, and it is untouched
  in name, in members and in every reader of it.
- **Names symbols in `src/ai_assistant/core/types.py` and
  `src/ai_assistant/core/protocols.py`**, so it is a contract-surface decision and takes both
  review lenses (ADR-0015 §1). It is **not** a breaking change and it authorises no
  implementation work: the name it rules is already on the tree, which §4 owns.
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
the reconciliation is owed. **This ADR is that reconciliation.** PR #2315 is not merged at this
ADR's base (`origin/main` `2ce4c193`), and its merge is sequenced ahead of this one, so the
record §5 lays on ADR-0251 is written to stand beside that note and to replace what it records.

### The tree, read rather than assumed, at `origin/main` `2ce4c193`

Three types, one file, and neither name is a draft:

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
`REFUSED` says a source that was reached decided not to answer, on a ground it owns (ADR-0251
§2). ADR-0185 §1's enum is the permission trail's record, durable on `SourceReadRecord` and read
by an operator; ADR-0251 §3's model is an in-process argument built from one turn's servicings
and discarded with the turn, minting nothing durable by its own clause. Neither is derivable
from the other. One name cannot carry both, and no reading of either ADR asks it to.

### What this ADR is not allowed to settle

- **Whether the two vocabularies should ever be reconciled, merged or ordered.** They are
  different facts (above) and this decision keeps them apart; anything further is a decision of
  its own.
- **Anything else of ADR-0251.** §§1-2 and §§4-18 are outside this ADR's scope entirely, and
  within §3 only the identifier moves.
- **Anything of ADR-0185.** §5 shows why no record is owed there.
- **Whether the implementation's order was acceptable.** §4 records what happened and what it
  does not license; it rules nothing about ADR-0015 §5, which is untouched.

## Decision

### 1. The model ADR-0251 §3 mints is named `ReadAskOutcome`

> **Normative.** The frozen model ADR-0251 §3 mints in `core/types.py` is named
> **`ReadAskOutcome`**. Wherever §3 writes `ReadOutcome` for that model — in its minting clause
> and in its parameter clause — the name an implementation writes, and the name a later ADR
> cites, is `ReadAskOutcome`.

> **Normative.** `core/protocols.py`'s `Planner.plan` parameter that ADR-0251 §3 replaces is
> annotated **`read_outcomes: Sequence[ReadAskOutcome] = ()`**. The parameter's name
> `read_outcomes`, its default `()`, its keyword position and its additive-in-shape character
> are ADR-0251 §3's and are not touched by this clause.

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

> **Normative.** ADR-0251 §2's `ReadOutcomeKind` keeps its name, its seven members and their
> values and meanings. Nothing in this decision reaches it, and the `outcome` field's type is
> `ReadOutcomeKind` exactly as §3 states.

### 3. ADR-0185 §1's `ReadOutcome` keeps the name, and the two are never conflated

> **Normative.** ADR-0185 §1's `ReadOutcome` — the `StrEnum` over how one gated source read
> ended — keeps its name, its six members and their values and meanings. No implementation and
> no later lane renames it, re-homes it, folds it into another vocabulary or re-uses it for
> anything but the record ADR-0185 §1 gives it.

> **Normative.** No implementation compares a member of one vocabulary with a member of the
> other, converts between them, or reads a value of one as a value of the other. `ReadOutcome`
> and `ReadOutcomeKind` are both `StrEnum`s whose values intersect in `refused` and `failed`,
> so such a comparison succeeds at run time and means nothing; the annotation is what keeps
> them apart.

### 4. The implementation preceded this decision, and this ADR records that rather than curing it

> **Normative.** This decision authorises no implementation work and no further contract
> change. The name it rules is already on the tree — `ReadAskOutcome` in `core/types.py` and
> `read_outcomes: Sequence[ReadAskOutcome] = ()` on `Planner.plan` — so the change that ratifies
> this ADR alters no file under `src/`, and no lane cites this ADR as ground for one.

**What happened, stated plainly.** ADR-0251 was ratified and merged as its own PR before its
implementation, exactly as golden rule 5 and ADR-0015 §5 require. Its §3 then turned out to be
unimplementable as written, and the L1 lane could not both implement §3's clause and leave
ADR-0185 §1's ratified, wire-visible, audit-read enum standing. It chose the second, spelled the
new model in full, and filed #2281. So the *name* on the tree has run ahead of the decision that
rules it since PR #2287 merged, and this ADR is the decision catching up.

**Why that is recorded here and not quietly fixed.** The order ADR-0015 §5 fixes exists so that
nothing implements against an unreviewed contract, and the exposure here is real but bounded:
what went unreviewed was one identifier, chosen to avoid a collision the ADR's author did not
see, disclosed in the type's docstring, in a test and on an open issue from the day it landed.
The alternative available to that lane was to implement §3 literally and shadow ADR-0185 §1 —
which is the outcome ADR-0015 §5 exists to prevent, reached by obeying it. Recording the
irregularity is the remedy that is actually available once the code has merged; pretending the
decision came first is not.

**And it licenses nothing.** ADR-0015 §5 is untouched by this ADR (§5). A lane that finds a
ratified contract clause unimplementable still stops, records what it found and asks — which is
what PR #2287 did — rather than reading this ADR as permission to land a contract surface no
ADR has ruled.

### 5. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's, applied to the earlier ADR's text: would a reader holding
only that ADR now act differently, or read one of its clauses more widely than it now holds?

- **ADR-0251 — a record is owed, and it is a partial supersession.** A reader holding §3 writes
  `ReadOutcome` into `core/types.py` and `Sequence[ReadOutcome]` onto `Planner.plan`; a reader
  holding this ADR writes `ReadAskOutcome` and `Sequence[ReadAskOutcome]`. That is acting
  differently on the decision itself, so under ADR-0070 §1 it is a supersession and not an
  amendment, and it is **partial** — one clause's identifier, nothing else (§3 of ADR-0070
  makes the partial form first-class). ADR-0251's `Status` takes the leading
  `Partially superseded by` token with the scope naming exactly what was replaced (ADR-0070
  §4), and the record itself lives in the appended dated note (ADR-0082 §2, ADR-0070 §1). That
  note replaces what PR #2315's note of 2026-09-13 records — that note states the divergence and
  decides nothing, and this one decides it — and where both stand, the earlier note's text is
  left unrewritten beside it, which is what the append-only mechanism requires (ADR-0070 §1).
- **ADR-0185 — nothing is recorded, and nothing is owed.** No clause of ADR-0185 §1 becomes
  false or over-wide. Its enum keeps its name, its six members, its totality claim, its
  `SourceReadRecord` home and every consumer rule §1 states about it; a reader holding ADR-0185
  alone acts identically before and after. Under ADR-0082 §1 that is the stacked-addition case
  — the obligation this ADR adds is recorded in the ADR that makes it and nowhere else — and
  §1 is explicit that a record may not be demanded on book-keeping grounds absent such a clause.
  §3 above states an obligation *about* ADR-0185 §1's enum without changing what ADR-0185
  decided.
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
  same change that ratifies it. The line is one physical line, the leading token leads,
  `Accepted` is dropped, and the scope names a clause and carries no `ADR-NNNN` token, so
  ADR-0070 §4's extraction invariant holds (every `ADR-NNNN` after the leading token is a
  target).
- **ADR-0251's appended dated note.** ADR-0070 §1 requires it in every case and permits "adding
  a dated header note"; ADR-0082 §2 puts the record in the note where the line carries the
  leading token. ADR-0001's own header is the precedent for the form.

**No ratified decision text is rewritten anywhere.** ADR-0251's Context, Decision and
Consequences are byte-identical after this change, PR #2315's note is left standing and
superseded rather than edited, and no mark is added to any ratified ADR (ADR-0089 §5).

### 7. Marking, review and ratification

This ADR is **marked** (ADR-0089): §§1-4 carry `> **Normative.**` clauses, and under ADR-0089 §3
those clauses are the whole of what it obligates — the prose beside them is read to determine
what they mean and supplies no obligation of its own. §§5-6 are classification of this change
and are deliberately unmarked (ADR-0089 §1).

It names symbols in `core/types.py` and `core/protocols.py`, so it is a **contract-surface
decision**: it takes both the adversarial and the architecture lens (ADR-0015 §1), is reviewed
while `Proposed`, and is ratified in this same PR by the isolated one-line `Proposed` →
`Accepted` flip ADR-0165 exempts from a fresh round.

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

**Follow-on work.** Two docstrings and one test module docstring on the tree say the name is
"this lane's and the ADR's is `ReadOutcome`" — `ReadAskOutcome`'s own docstring in
`core/types.py`, and the header of `tests/core/test_read_outcome_types.py`. Those sentences go
stale the moment this ADR is accepted, and correcting them is outside this docs-only change's
fence; it is filed as its own issue rather than folded in.

**What would trigger revisiting this.** A decision that gives the two vocabularies one home, or
an ADR that retires ADR-0185 §1's enum, would make the collision this ADR routes around
disappear; §1 would then be the only thing naming the model, and a fresh decision could rename
it freely.

## Alternatives considered

**Rename ADR-0185 §1's enum instead, and give §3 the name it asked for. Rejected.** It is the
only other way to seat both types in one module, and it is worse on every count. ADR-0185 §1's
`ReadOutcome` is **ratified, implemented and wire-visible**: it is a field type on
`SourceReadRecord`, it is read by the audit path and by an operator-facing surface, and its six
members are asserted total over ADR-0097 §5 and ADR-0093 §8's outcomes. Renaming it would be a
breaking contract change touching a persisted record's type, owed its own migration reasoning,
in order to free a name for a model that is an in-process argument discarded with the turn. And
the collision was **the later ADR's to avoid**: ADR-0185 held the name for eleven weeks and
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
