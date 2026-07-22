# 40. Reinforcement and supersession are different rulings

- Status: Proposed
- Date: 2026-07-22
- **Contract change.** `MemoryDecisionKind` and `MemoryDecision` are `core` types
  that cross subsystem boundaries, so this ADR ships as its own PR and is
  ratified before anything implements against it (golden rule 5, ADR-0015 §5,
  `CONTRIBUTING.md` → "Contract ADRs land before their implementation"). No code
  changes with it.
- **Amends on ratification:** [ADR-0038](0038-a-user-assertion-supersedes-a-conflicting-inference.md)
  §1b, and the §Consequences entries that depend on it. ADR-0038 §1b nominates
  issue #256 as its own removal; this is that removal. Also amends
  [ADR-0028](0028-the-memory-write-path-is-a-contract.md) §8's conformance list,
  which excludes fold semantics from the `MemoryWriter` contract — see §5a.
  Neither edit is made by this change — see §Consequences for their exact form
  and why they wait.
- **Follow-up to** [ADR-0005](0005-memory-model.md) §3, which established that a
  policy disposes and the `memory` subsystem applies. This ADR restores that
  separation where ADR-0038 had to breach it.

## Context

ADR-0005 §3 splits the write path in two: a deterministic `MemoryPolicy`
*disposes* — it rules on a proposal — and `memory` *applies* the ruling. The
split only works if the ruling carries everything the applier needs.

It does not. `MemoryDecisionKind.MERGE` is one ruling for two opposite relations
between the incoming record and the target it names:

- **reinforcement** — the two records *agree*. `MemoryIngestor._merge` unions
  `Provenance.evidence` and takes the maximum `confidence`, "so a merge
  strengthens rather than weakens what is known."
- **supersession** — the incoming record *overturns* the target.
  `MemoryIngestor._supersede` carries nothing across, because ADR-0005 §2 defines
  `evidence` as references *supporting* the record, so attaching the observations
  that produced the wrong belief to the record that corrects it is a fabricated
  warrant (ADR-0038 §1a).

`MemoryDecision` has no field in which to say which one was meant. So ADR-0038
had to have `MemoryIngestor` *infer* the relation from the two records'
provenance — an incoming `USER_ASSERTED` record landing on a derived one is read
as supersession, anything else as reinforcement. ADR-0038 §1b records this
plainly as a precondition rather than a derivation: only the policy knows which
relation it meant, and the contract gives it no channel to say so. Both review
personas on PR #246 raised it as a blocker; it was overridden deliberately so a
real product defect could ship, on the condition that this ADR follow.

### What is actually still exposed

Narrower than issue #256's text implies, because ADR-0038's implementation moved
the *unrecoverable* refusals out of the policy and into `MemoryIngestor`, keyed
on the records and applied before either fold is selected. `_refuse_unsafe_fold`
raises for **any** fold onto a `USER_ASSERTED` target and for a `USER_ASSERTED`
proposal onto an `EXTERNAL` one, for every injected policy, guard or no guard.
Both hazards issue #256 lists as adversarial and architecture findings are
therefore already closed at the boundary that performs the write.

What remains behind the precondition is one **recoverable** case: a policy
returns the merge ruling for a `USER_ASSERTED` proposal onto an `OBSERVED` or
`INFERRED` target *meaning reinforcement* — an asserted restatement of something
we had inferred — and the ingestor reads it as supersession and discards that
record's `evidence` list. The record itself survives, at its id, carrying the
user's own words at confidence 1.0. What is lost is the derived record's audit
trail, on a belief that is by construction re-derivable (ADR-0038 §2): the
observations that produced it can produce it again.

That is the whole live defect. It is small, and it is not the reason to act.

### Why it is worth a contract change anyway

Three reasons, none of which is the size of the loss.

1. **The rule is in the wrong subsystem.** ADR-0005 §3 puts the judgement in the
   policy and the application in `memory`. Today `memory` re-derives the
   judgement from data, which means the disposition seam is not carrying the
   disposition. Every future rule about *which* fold happens has to be written
   twice, once in the policy that decided and once in the ingestor that guesses.
2. **The precondition is unenforceable where it matters.** ADR-0038 §1b's guard
   in `tests/memory/test_ingest.py` enumerates `MemoryPolicy` implementations
   *inside the `memory` subsystem*. A policy defined anywhere else — the whole
   point of an injected seam — is invisible to it. The guard is honest about
   this; it is a check on what this repository ships, not on the contract.
3. **It blocks issue #112.** Bi-temporal validity has to settle "invalidation
   ruling versus `MERGE`" as its own open question 2. It will settle it worse if
   it inherits a ruling that already means two things.

The forces against acting are real too. `MemoryDecisionKind` has five members and
three consumers, all in this repository; churn on a `core` enum reaches the
conformance suite, both canonical fakes, and every construction site. And there
is a live argument that issue #112 makes this ADR unnecessary, which §6 rules on.

## Decision

### 1. A ruling names the relation the policy asserts, never the write it causes

We will replace `MemoryDecisionKind.MERGE` with **two** members, named for the
relation between the incoming record and the target:

- **`REINFORCE`** — the incoming record agrees with the target and strengthens
  it. The applier folds: newest content wins, `evidence` is unioned, `confidence`
  is the maximum. This is `_merge`, unchanged.
- **`SUPERSEDE`** — the incoming record overturns the belief the target holds.
  The applier retires what the target held and takes nothing from it. This is
  `_supersede`, unchanged.

`MERGE` is **removed**, not retained with a narrowed meaning (§2 argues why).

The naming rule is load-bearing and not cosmetic: **the member names the
relation, not the mechanism.** `MERGE` named a mechanism — fold two records —
which is why it could not distinguish two relations that happen to share it
today. A relation-named ruling stays true when the mechanism changes: under issue
#112, `SUPERSEDE` closes the target's validity window and writes a new record
instead of overwriting at the target's id, and neither the member nor any policy
that returns it needs to change. That property is the reason §6 can rule the way
it does.

Nothing else about the ruling changes. Both members carry a target id; both
commit; the four remaining members (`ACCEPT`, `REJECT`, `ASK_USER`,
`STORE_TEMPORARY`) are untouched.

### 1a. One target field, renamed to `target_id`

`MemoryDecision.merge_into` becomes **`target_id`**, required for `REINFORCE` and
`SUPERSEDE`, forbidden otherwise. The existing `_outcome_fields_are_consistent`
validator widens its first branch from one kind to two and is otherwise unchanged.

One field rather than two (`merge_into` plus a new `supersedes`): the two rulings
name the same thing — an existing record id drawn from the `conflicts` the policy
was handed — and splitting it would give one concept two nullable fields, a
cross-field validator to keep exactly one populated, and a `decision.merge_into or
decision.supersedes` at every read site.

Renamed rather than kept, because `merge_into` is an instruction to perform the
mechanism §1 just stopped naming. A policy author writing
`SUPERSEDE(merge_into=...)` is being told the wrong thing about what will happen
to that record. `target_id` says only what it is: the record this ruling is about.

`MemoryDecision` is never serialised — it is returned inside `MemoryIngestResult`
and read in-process, and only `MemoryRecord` reaches `SqliteMemoryStore` — so
neither the field rename nor the enum change has a stored-data migration.

### 2. `MERGE` is removed, so every site must be re-decided by hand

The additive option — keep `MERGE` meaning reinforcement, add `SUPERSEDE` — is
the one issue #256 lists first and the one we reject.

**It fails silently in both directions.** A `MemoryPolicy` written before this
change that returns `MERGE` to mean supersession keeps type-checking and keeps
running, and now gets the opposite fold: the overturned belief's evidence unioned
onto the record that corrects it, which ADR-0038 §1a calls a fabricated warrant
and rates worse than the stale record ADR-0038 exists to remove. In the other
direction, every applier in this repository dispatches on the kind with a
trailing `case _` that writes nothing:

- `MemoryIngestor._apply` — `case _:  # REJECT, ASK_USER — nothing is written.`
- `FakeMemoryWriter._apply` — the same shape.

An added member falls into that arm. A `SUPERSEDE` decision would return
`record_id=None` and write nothing, while the caller receives a `MemoryIngestResult`
that reports a healthy ruling. `match` over a `StrEnum` is not exhaustiveness-checked,
so nothing in the gate catches it — and the canonical fake failing this way is
precisely the trap `FakeMemoryWriter` names in its own docstring: "a consumer's
test pass[ing] on state `MemoryIngestor` would have refused".

Removal makes both loud. `MemoryDecisionKind.MERGE` becomes an attribute error
under `mypy --strict` at every construction site, so the gate lists exactly the
places whose *meaning* has to be re-decided — which is the actual work of this
migration. This is the same fail-closed preference the write path already
applies: a `MERGE` naming an absent target raises rather than storing the
proposal as new, and `_refuse_unsafe_fold` raises rather than downgrading,
both because a write that reports success while losing data is worse than one
that stops.

The cost is that every `MemoryDecisionKind.MERGE` in the repository is touched.
There are six references in `src/` outside the enum's own definition, across four
files, plus their tests — all enumerated in §Consequences. Nothing outside this
repository implements `MemoryPolicy`.

### 3. The ingestor stops inferring, and its refusals do not move

`MemoryIngestor._apply` gains a `SUPERSEDE` arm and loses the provenance test
that currently chooses between the two folds. `REINFORCE` routes to `_merge`,
`SUPERSEDE` to `_supersede`, with no reading of either record's source.

**`_refuse_unsafe_fold` stays exactly where it is and stays keyed on the
records.** This is the part of ADR-0038 most likely to be undone by an
implementer who now has the relation available on the decision, so it is stated
as a decision rather than left as inherited code:

- it still runs **before** either arm is selected, for both rulings;
- it still tests the *target's* source and the *incoming* record's source, not
  the relation between them.

ADR-0038 §2a's argument for that is unchanged by this ADR and is worth restating:
neither refused case is a supersession, so a refusal gated on "is this a
supersession?" lets both fall through into the reinforcing fold — which keeps the
target's id and destroys it just as thoroughly. Every fold overwrites the target,
so the target is what has to be checked. Making the relation declarable does not
make the policy trustworthy about it; the ingestor takes rulings from any
injected implementation, and a safety property may not rest on the ruling it is
protecting against.

Consequently ADR-0038 §3 — an inference may never supersede an assertion —
survives this change untouched and unweakened, and is now the only thing standing
between a policy and a destructive write, rather than one of two.

### 4. `DefaultMemoryPolicy` migrates with no behavioural change

Its two merge sites are re-labelled, and neither changes what it returns for any
input:

- **rule 3**, `_rule_on_assertion` — a user assertion over the best-ranked
  `OBSERVED`/`INFERRED` conflict — becomes `SUPERSEDE`. This is what
  `MemoryIngestor` already does with it; the ruling now says so.
- **rule 5** — a non-asserted proposal that conflicts with a non-asserted record,
  reason "updates an existing memory" — becomes `REINFORCE`. This is also what
  the ingestor already does with it.

Rule 5 is the uncomfortable one and we are labelling it honestly rather than
quietly. Those records were paired because they are *topically similar*, which
ADR-0038 §2 is explicit is not contradiction; calling the ruling `REINFORCE`
asserts they agree, and sometimes they will not. That mislabelling is not created
here — `_merge`'s union-and-maximise has been rule 5's behaviour since ADR-0005,
and this ADR only makes it legible. Whether rule 5 should sometimes supersede is
a question about `DefaultMemoryPolicy`'s reasoning, decidable in the policy lane
once the vocabulary exists, and it is filed rather than answered here (§7).

The new member also widens what a *conforming* policy may express beyond
`DefaultMemoryPolicy`'s rule 3: `SUPERSEDE` is defined by the relation, not by
the proposal's source, so a policy may declare that a high-confidence `OBSERVED`
record overturns an `INFERRED` one. That is deliberate — the contract should not
encode one implementation's rules — and it is bounded by §3's refusals, which are
what actually protect the unrecoverable cases.

### 5. The conformance suite widens a predicate; it gains no obligation

The `MemoryPolicy` conformance suite currently asserts, of `MERGE`, only what
the contract already states: that a target-carrying ruling names one of the
records `decide` was actually handed, and that a policy with no conflicts cannot
return one. Those three assertions and the `_COMMITTING` set change from naming
`MERGE` to naming `{REINFORCE, SUPERSEDE}`. That is a mechanical widening of a
predicate over the same obligation.

**The suite must not assert which relation a policy picks.** A conformance suite
*is* the contract (issue #40): asserting that an asserted proposal over a derived
conflict earns `SUPERSEDE` would refuse a policy that genuinely conforms and
would widen the contract past what this ADR ratifies. The suite's existing note —
that it deliberately encodes no particular ruling, and that ADR-0038 rewrote
`DefaultMemoryPolicy`'s answers without touching a line of it — is the property to
preserve. `DefaultMemoryPolicy`'s specific rules stay in `test_policy.py`.

### 5a. The `MemoryWriter` contract gains one differential obligation

`MemoryPolicy` is only half the seam. `MemoryWriter` (ADR-0028) is how
`orchestration` reaches this write path, and its shared conformance suite is what
makes two writers interchangeable. ADR-0028 §8 deliberately excludes "the fold's
own rule" from that suite, on the grounds that folding is `memory`'s semantics
and a suite pinning it would stop being a contract. That reasoning was right and
this ADR breaks one piece of it.

Once `REINFORCE` and `SUPERSEDE` are distinct `core` members, the *difference*
between the two folds stops being an implementation choice and becomes what the
members mean. A second `MemoryWriter` could route both rulings through a single
union-fold, keep the target's id, return it, and pass every obligation ADR-0028
§8 lists — while doing to a `SUPERSEDE` exactly what ADR-0038 §1a calls a
fabricated warrant. The distinction would be declarable on the decision and
unenforceable at the boundary that acts on it: the same defect this ADR removes,
relocated from the policy side to the applier side.

So the `MemoryWriter` conformance suite gains obligations that pin what each
ruling *means*, and they are deliberately asymmetric:

> **`SUPERSEDE` carries nothing of the target onto the surviving record.** After
> a `SUPERSEDE`, the live record is the proposed record — its content, its
> provenance, its `evidence`, its `confidence` — borrowing from the target only
> the id it is written at.
>
> **`REINFORCE` retains the target's `evidence`.** Everything else about the
> fold is unasserted.

The asymmetry is not an oversight, and an earlier draft of this section got it
wrong by stating only the evidence half of each. `SUPERSEDE` admits a *complete*
specification because "take nothing across" is complete — there is no fold to
leave open, so a writer that kept the target's content or confidence while
dropping its evidence would pass a differential-on-evidence check and still not
have overturned anything. `REINFORCE` does not admit one: which content wins and
how confidence combines is exactly the fold rule ADR-0028 §8 leaves to `memory`,
and pinning it here would be the over-correction that stops the suite being a
contract. Evidence retention is singled out because it is the one effect that
distinguishes the two rulings, and it is ratified *here* rather than invented by
the suite — the mistake §5 and issue #40 guard against.

Everything else ADR-0028 §8 excluded stays excluded: content precedence,
confidence maximisation, `last_updated`, the conflict threshold and limit, and
the tuning check remain `memory`'s own and unasserted.

**The id clause is the one mechanism statement here, and it is temporary.** "The
surviving record is written at the target's id" is ADR-0038 §1's choice, not
something `SUPERSEDE`'s *name* implies, and §6 is explicit that issue #112
replaces it with "close the target's window and write a new record". It is
asserted anyway, because it is true of every writer that can exist today and an
unasserted id is how a `SUPERSEDE` that silently wrote nowhere would pass. It is
marked in the suite as the obligation #112 rewrites — see the correction to §6
below, which an earlier draft of this ADR got wrong by claiming the whole seam
survived #112 untouched.

`FakeMemoryWriter` therefore has to grow a real supersession path to pass its own
suite, which is the divergence §Consequences already requires it to close.

Whether `_refuse_unsafe_fold`'s two refusals should *also* become `MemoryWriter`
obligations is a real question, and it is **not** decided here. Its argument is
ADR-0038 §2a's and it is not caused by splitting the enum — that refusal is keyed
on the records and would read identically under either contract. Filed on
ratification rather than answered, so this ADR does not absorb a second
widening of a contract it is not about.

### 6. Ruling: issue #112 does **not** subsume this, and this narrows #112

Issue #112 (bi-temporal validity: invalidate, don't delete) is the right frame
for four of ADR-0038's five compromises, which ADR-0038 §6 says plainly. It is
not the right frame for this one, and folding this into it — issue #256's option
3, and the reading the lane that hit this arrived at — would be a mistake.

**They are about different halves of the write path.** #112 decides what the
*store* does to a record that stops being true: close its validity window instead
of overwriting it, filter it out of `get`/`search`, keep it for `export`. This
ADR decides what the *policy* is able to say. Bi-temporality does not remove the
ambiguity — under a validity window, a ruling that names a target still has to
say whether the incoming record strengthens that record (one live record, unioned
evidence) or invalidates it (two records on disk, one live). Those remain
opposite operations, and `MERGE` remains one name for both. #112's own open
question 2 — "invalidation ruling vs. `MERGE`?" — is this question, arriving
inside a much larger change.

**Landing this first makes #112 smaller and safer.** Because §1 names the member
for the relation and not the mechanism, `SUPERSEDE` is already the ruling #112
wants: bi-temporality changes how the applier *executes* it, and leaves the
member, `MemoryDecision`, `DefaultMemoryPolicy` and the `MemoryPolicy`
conformance suite untouched. #112 then decides record fields and store read
semantics, which is what it is actually about.

**One seam does move, and this ADR names it rather than claiming otherwise.**
§5a's `MemoryWriter` obligation that a `SUPERSEDE` is written at the target's id
and returns it is the mechanism #112 replaces: under a validity window the
applier closes the target's window and writes a *new* record, so the suite's id
clause becomes "returns the id of the live record" and `MemoryIngestResult`
carries a different id than it does today. That belongs to #112 and is the right
shape for it — it is an obligation about what the applier does, which is #112's
whole subject, and it is the *only* obligation in either suite that #112 has to
revisit. The claim being made is that this ADR leaves #112 one clause to rewrite,
not none. The reverse order costs more: #112 would ratify a decision-kind change as
a side effect of a records-and-reads change, with the migration of every existing
`MERGE` site (§2) buried inside it.

**Nothing here is a parallel mechanism #112 would unpick.** This ADR adds no
field to `MemoryRecord` or `Provenance`, no store semantics, and no history
representation. It renames one field on `MemoryDecision` and splits one enum
member. ADR-0038 §1a's discard of displaced evidence stands unchanged and is
still the thing #112 gives back first.

**The neighbouring issues do dissolve into #112, and this one is why they can.**
#244 (supersede N conflicts, not one) becomes "close N windows" and stops needing
`target_id` to grow to a list. #254 (a correction cannot supersede an `EXTERNAL`
record) is entirely an id-discipline problem — supersession inherits the
integrating system's idempotency key — and disappears when supersession stops
writing at the target's id. #245 (two contradictory assertions both stay live)
needs a validity window to resolve at all. All three are about *what happens to
the record*; #256 is about *what the policy said*. That is the line, and it is
why three of the four move and one does not.

### 7. What this ADR does not decide

- **Whether `DefaultMemoryPolicy` rule 5 should supersede** in some cases (§4).
  Filed as an issue on ratification; it is a policy-lane question that this
  vocabulary makes askable, and answering it here would smuggle a behavioural
  change into a contract ADR.
- **Whether `_refuse_unsafe_fold`'s refusals belong on the `MemoryWriter`
  contract** (§5a). Filed on ratification; its argument is ADR-0038 §2a's and it
  is not caused by this change.
- **Anything in #112's scope** — validity fields, store read filtering, as-of
  queries, `export` semantics, schema migration (§6).
- **The lost-update window** in `MemoryIngestor.ingest` (issue #248). Unaffected
  either way: it is a race in the applier, not an ambiguity in the ruling.
- **The unratified `MemoryPolicy` expectations** of issue #40 (input
  immutability, non-blank `reason`). Adjacent, separately scoped.

## Consequences

- **The disposition seam carries the disposition.** ADR-0005 §3's split holds
  again: the policy says which relation it means and `memory` applies it. The
  ingestor stops reading provenance to recover intent, and a future rule about
  which fold happens is written once.
- **ADR-0038 §1b's precondition retires, and so does its guard.** The
  amendment to ADR-0038 lands with the implementation PR, not with this ADR
  (ADR-0001: ADRs are append-only, and a status or cross-reference edit is a
  trivial change that travels with the work it describes). Its form: §1b is
  annotated as discharged by this ADR, and the §Consequences entries "**`MERGE`
  now means two different things at the ingestor**", "**Writing a new
  `MemoryPolicy` now carries a constraint that is not on the Protocol**", and the
  "**Revisit when** issue #256…" clause are marked as closed here. ADR-0038's
  §1a, §2, §2a, §3, §4 and §5 rulings are unchanged; only the inference machinery
  in §1b goes.
- **This is a breaking `core` change**, flagged per golden rule 5. Every
  construction site of `MemoryDecisionKind.MERGE` and every reader of
  `merge_into` fails the gate until updated — which is the intent (§2), since
  each one's meaning is what has to be re-decided.
- **The implementation PR owes**, in one change (contract, conformance suite and
  canonical fakes are one unit of work):
  - `core/types.py` — `MemoryDecisionKind`: drop `MERGE`, add `REINFORCE` and
    `SUPERSEDE`. `MemoryDecision`: rename `merge_into` to `target_id` and widen
    `_outcome_fields_are_consistent` to require it for both members and forbid it
    for the other four. No change to `MemoryPolicy` or `MemoryWriter` in
    `core/protocols.py` — the Protocol signatures are untouched; only the type
    they carry changes.
  - `memory/policy.py` — rule 3 → `SUPERSEDE`, rule 5 → `REINFORCE`, and the
    class docstring's numbered rules re-worded to match (§4). No behavioural
    change; `tests/memory/test_policy.py` changes only the kind it asserts.
  - `memory/ingest.py` — a `SUPERSEDE` arm in `_apply`; delete the
    `proposed.provenance.source is USER_ASSERTED` test and the ADR-0038 §1b
    comment block above it. `_refuse_unsafe_fold`, `_merge` and `_supersede` keep
    their bodies; `_merge`'s "reinforcement only" precondition becomes a
    statement about which ruling reaches it rather than a caveat (§3).
  - `testing/policy.py` — `FakeMemoryPolicy` handles both members wherever it
    handles `MERGE` today: the no-conflicts fallback to `ACCEPT` and the
    `conflicts[0]` target selection apply to each.
  - `testing/writer.py` — `FakeMemoryWriter` gains a `SUPERSEDE` arm. **It has
    no supersession path at all today**: its `MERGE` arm folds via its local
    `_merge` for every proposal, so it already diverges from `MemoryIngestor`
    for a user assertion (ADR-0038 updated the ingestor and not the fake). The
    implementation PR closes that divergence, including `_refuse_unsafe_fold`'s
    two refusals, so a consumer's test cannot pass on state the production writer
    would have refused — the obligation the fake's own docstring states.
  - `tests/memory/memory_policy_contract.py` — `_COMMITTING` and the three
    target-coherence assertions widen from `MERGE` to both members, and nothing
    else (§5).
  - `tests/memory/memory_writer_contract.py` — split what it asserts of `MERGE`
    across the two rulings rather than widening it uniformly. Both keep "raises
    `MemoryStoreError` on a target absent from the conflicts" and, per §5a,
    "written at the target's id, which is returned" — the latter marked in the
    docstring as the clause issue #112 rewrites. `REINFORCE` keeps the fold and
    gains the evidence-retention obligation; `SUPERSEDE` gets §5a's complete
    one — the live record equals the proposed record but for its id. The module
    docstring's obligation list is rewritten to match, since it currently states
    the `MERGE` obligations verbatim.
  - `docs/adr/0028-*.md` — §8's conformance list amended to record that
    exclusion of the fold's rule now carries §5a's exception. ADR-0028's other
    rulings are unchanged.
  - `tests/memory/test_ingest.py` — delete `_production_memory_policies`,
    `test_the_policy_scan_actually_finds_the_shipped_policies` and
    `test_a_shipped_policy_merges_an_assertion_only_into_a_derived_record`; that
    is ADR-0038 §1b's guard and it has nothing left to guard. **Keep**
    `test_the_default_policy_actually_supersedes_so_the_guard_is_not_vacuous`,
    retargeted to `SUPERSEDE` — it pins ADR-0038 §1, not the precondition — and
    **keep** every test of `_refuse_unsafe_fold`, including
    `test_a_correction_survives_the_next_external_re_sync` and
    `_MergeEverythingPolicy`, which exercise the boundary §3 leaves in place.
    Add the case this ADR exists for: a policy returning `REINFORCE` for a
    `USER_ASSERTED` proposal onto an `INFERRED` target keeps that target's
    evidence.
  - `docs/adr/0038-*.md` — the amendment above.
- **Issue #256 closes with the implementation PR.** Issue #112 loses its open
  question 2 and keeps the rest.
- **A policy can now express a relation the default policy does not use** (§4).
  That is contract surface with no shipped consumer, which is the usual cost of
  putting a judgement where it belongs.
- **Revisit if** #112 ratifies a validity window and `SUPERSEDE`'s applier
  changes shape (the member and every policy returning it should survive that
  untouched — if they do not, §1's naming rule was wrong), or if a third relation
  appears that a target-carrying ruling has to express, at which point the same
  question is asked again with the same answer.

## Alternatives considered

- **Keep `MERGE`, add `SUPERSEDE`** (issue #256, option 1). Rejected in §2: it is
  additive precisely where the failure is silent. Pre-existing policies keep
  compiling and get the opposite fold, and both appliers' trailing `case _`
  swallow the new member into a no-op that reports success. The migration this
  change *is* — re-deciding what each existing merge site meant — is the part it
  skips.
- **A flag on `MemoryDecision`**, e.g. `overturns: bool` or a `MergeRelation`
  enum field, keeping one kind (issue #256, option 2). Rejected: it puts a
  discriminator beside the discriminator. `MemoryDecisionKind` already exists to
  say what the applier should do, appliers already `match` on it, and a second
  field means every reader handles a nested two-case dispatch that the enum
  handles natively. It is also under-constrained — the flag is meaningless for
  four of the five kinds, needing another validator branch to forbid it there —
  and it leaves `MERGE` in place as a name for a mechanism, which §1 rejects on
  its own grounds. A boolean would additionally be unextendable to a third
  relation.
- **Fold into issue #112's invalidation ruling** (issue #256, option 3; the
  reading ADR-0038 §1b itself calls most likely). Rejected in §6: different
  halves of the write path, and #112 does not remove the ambiguity — a
  target-carrying ruling under a validity window still has to say whether it
  strengthens or invalidates. Landing this first makes #112 strictly smaller.
- **Do nothing; keep the precondition and its guard.** Rejected, but it is the
  closest call, because the live loss is one recoverable evidence list (§Context).
  What decides it is that the precondition cannot be enforced where the risk is
  — the guard cannot see a policy defined outside `memory`, which is the only
  kind of policy the injected seam exists to allow — and that #112 has to answer
  this question regardless. Deferring means answering it inside a larger change.
- **Widen `MemoryPolicy`'s conformance suite to require the relation instead of
  changing `core`.** Rejected: a conformance suite is contract (issue #40), so
  this widens the contract without ratifying it and refuses a policy that
  genuinely conforms. It is also the mistake ADR-0038 §1b explicitly declined to
  make, and it would not help — the suite runs on implementations someone chose
  to test, not on the one injected at runtime.
- **Keep the field name `merge_into` for both rulings.** Rejected in §1a: it
  instructs a `SUPERSEDE` applier to perform the fold `SUPERSEDE` exists not to
  perform. Cheap to keep, and it re-creates in one field the exact conflation the
  enum change removes.
- **Widen the `MemoryWriter` suite mechanically and leave fold semantics
  implementation-local**, per ADR-0028 §8 as written. Rejected in §5a: a second
  writer could then route both rulings through one union-fold and conform, which
  makes the distinction declarable but unenforceable — this ADR's own defect,
  moved from the policy side to the applier side. The opposite over-correction —
  pinning both rulings' fold rules — is rejected with it, for ADR-0028 §8's
  original reason. §5a takes neither: it specifies `SUPERSEDE` completely, since
  "carries nothing across" is a complete specification and a partial one lets a
  writer keep the target's content and still pass, and of `REINFORCE` it pins
  only the evidence retention that distinguishes the two.
- **Two target fields, `merge_into` and `supersedes`.** Rejected in §1a: one
  concept, two nullable fields, a cross-field validator to keep exactly one
  populated, and a disjunction at every read site.
