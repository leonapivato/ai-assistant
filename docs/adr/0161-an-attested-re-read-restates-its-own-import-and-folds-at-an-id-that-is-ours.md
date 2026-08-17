# 161. An attested re-read restates its own import, and folds at an id that is ours

- Status: Proposed
- Date: 2026-08-16
- **This ADR partially supersedes**
  [ADR-0159](0159-a-conflict-is-labelled-before-it-is-ruled-on-and-similarity-alone-folds-nothing.md)
  §4 and §6, in the scope §1 names and in no other. **Of §4:** §4(a) whole — its
  target class, its target selection and the reach of its `CONTRADICTS` purity
  condition — and the paragraph excluding `EXTERNAL` from both target classes, each
  only as it reaches a proposal whose own `provenance.source` is `EXTERNAL`. **Of
  §6:** the set of members its degraded floor may name as a target, for every
  non-asserted proposal and not only an `EXTERNAL` one, since §6 states no class and
  §1 now states one for it (§8). §4(b) and its purity condition, §4(c), the
  `ASK_USER` precedence, §6's degradation ruling and every other section of ADR-0159
  stand.
- **This ADR amends** [ADR-0110](0110-a-covered-readings-absence-closes-a-window-and-a-clock-never-does.md)
  §4 — the mechanical sentence it appends to its presence rule, not the rule (§8).
- **No contract surface moves.** No Protocol gains a member, no signature changes,
  and `core/types.py` is untouched: this ADR moves one arm of one
  `MemoryPolicy` implementation. **Both review lenses are run anyway**, because it
  amends the ruling a contract ADR ratified eight days into its own implementation
  lane, and the architecture lens is the one whose subject is a decision.
- Refs #1198 (the case, filed by ADR-0159's implementing lane), #1190. Files #1203
  and #1204 in §9. Cites #736, #743, #827, #870.

## Context

### The exclusion and the presence rule it defeats

ADR-0159 §4 keeps `EXTERNAL` out of **both** target classes of
`DefaultMemoryPolicy`'s non-asserted arm, and gives one reason for both:

> **`EXTERNAL` is in neither target class, and the reason is ADR-0121 §3's, unchanged.**
> A `REINFORCE` folds at the *target's* id, an imported record's id is the
> integrating system's idempotency key, and the next routine sync overwrites the
> fold — so a fold onto an import is futile whatever the incoming source is.

ADR-0110 §4 rests its **presence** rule on exactly the fold that clause removes:

> **`ACCEPT` and `STORE_TEMPORARY` therefore need no exception, and it is worth
> saying why they do not.** Both install at the *proposal's* id, so neither can
> ever mark a §3 candidate present […] So an entry that re-appeared and did **not**
> fold leaves its predecessor absent and closes it. […] The unchanged entry, which
> must not take that path, does not — **ADR-0092 §6 puts it on `REINFORCE`, which
> folds at the target's id and marks it present.**

Compose the two. A scheduled read of a connected calendar re-proposes an unchanged
entry as an `EXTERNAL` record restating its own stored `EXTERNAL` predecessor. Under
§4 the arm finds no `OBSERVED` or `INFERRED` member, so it falls to (c) and rules
`ACCEPT`, which installs at the proposal's own freshly minted id. The predecessor is
now **absent** from a reading that in fact reported it, and the coverage close
retires it. Every scheduled read retires its entire previous set and re-installs it
at new ids.

`tests/readers/test_calendar_absence_end_to_end.py::test_repeated_identical_reads_fold_rather_than_minting_duplicates`
measures the size of that: three cycles leave six records where the ratified
behaviour leaves two, and its own docstring costs it out — "At a 20-second interval
that is thousands of unretrievable, un-demotable records per entry per day." Two
tests in `tests/memory/test_absence_reconciliation.py` fail beside it on the same
cause. #1198 records the reproduction; this ADR is not re-deriving it.

### Why §4's stated ground does not hold for this pairing

§4 imports ADR-0121 §3's argument, and ADR-0121 §3 made it about a **`USER_ASSERTED`**
proposal — its §2 arm, its §5 writer-floor exception, its §7 residue are all about a
user restating what an import already said. The argument's premise is a factual
claim about where an `EXTERNAL` record's id comes from, and on this tree that claim
is false for a conforming producer. ADR-0092 §6 rules the opposite in terms:

> **An `EXTERNAL` producer proposes each record at an id it mints, opaque to the
> source.** It may not use the source's own key — a VEVENT `UID`, a row id, a
> URL — as `MemoryRecord.id`, whether directly or namespaced.

and says what that buys: "**Minting removes the aim.**" `readers/calendar.py`'s
`_mint` implements it — its default is `f"calendar-{uuid4().hex}"` — and its
docstring draws the consequence the futility argument denies: "**Idempotency does
not vanish; it moves.** An unchanged re-read proposes the same content,
`_detect_conflicts` ranks the identical live record top, and `DefaultMemoryPolicy`
rules `REINFORCE`, which folds at the *target's* id."

So the next routine sync does not overwrite the fold, because the next routine sync
never computes the target's id. It cannot: the id is a `uuid4` we minted and the
source has never seen. The futility argument is sound for a **foreign-keyed** import
and does not reach a **producer-minted** one, and ADR-0092 §6 is the ruling that
made every conforming import the second kind.

ADR-0159 §11 records nothing against ADR-0110 and §12 does not name it. The
interaction reads unweighed rather than decided, which is the ground on which
reopening it is not relitigation.

### What is not in question

Nothing here reopens ADR-0159's substance. The measurement stands — half of every
proposal the pilot's observer made was folded into a record that merely resembled
it (#1029, run `8a8f7a033b3c`) — and so does the inversion §4 makes: `ACCEPT` is the
default and each write is the exception. This ADR moves one class of one arm, on a
pairing whose fold is decided with no model at all.

## Decision

### 1. §4(a) admits an `EXTERNAL` target where the proposal is `EXTERNAL` and the two agree

> **Normative.** ADR-0159 §4(a) is replaced by: `REINFORCE`, naming as `target_id`
> the best-ranked **eligible** member, exactly when an eligible member exists and
> the purity condition below is satisfied for it. A conflict-set member is
> **eligible** when either (i) it is labelled `RESTATES` and its
> `provenance.source` is `OBSERVED` or `INFERRED`, or (ii) its `provenance.source`
> is `EXTERNAL`, the proposed record's `provenance.source` is `EXTERNAL`, its
> `provenance.attestation.reported_by` equals the proposed record's, and it
> **agrees** with the proposed record under ADR-0121 §1.

> **Normative.** ADR-0159 §4(a)'s purity condition — that no member is labelled
> `CONTRADICTS` — binds a target eligible only under (i), exactly as ADR-0159 §4(a)
> states it. It does not bind a target eligible under (ii), which is named whatever
> any other member of the set is labelled.

> **Normative.** Where the proposal's `provenance.source` is `EXTERNAL` and the set
> holds an eligible member under (ii), the target is that member — the best-ranked
> of them where several qualify — ahead of any member eligible only under (i).

> **Normative.** ADR-0159 §4(b) is untouched. `EXTERNAL` names no supersession
> target, whatever the proposal's source, and an `EXTERNAL` member counts in each
> purity condition exactly as any other member does — a member labelled `RESTATES`
> blocks (b), and a member labelled `CONTRADICTS` blocks (a) to the extent the
> purity clause above leaves that condition binding, which is a target eligible only
> under (i). ADR-0159 §4(c), the `ASK_USER` precedence, and the clause
> distinguishing the non-empty-set `ACCEPT` are unchanged.

> **Normative.** ADR-0159 §4's statement of what the arm reads is extended, for
> clause (ii) alone, by `kind` and `content` — through ADR-0121 §1's predicate — and
> by `provenance.attestation.reported_by`. It still reads no retrieval score, no
> threshold, and no rank other than to order members the clauses above have already
> selected.

**Clause (ii) is the certain rung and nothing above it.** ADR-0121 §1's `agrees` is
a syntactic predicate over `kind` and `content` — NFC, case folding, whitespace
collapse, strip — that "never reads a retrieval score, a `Provenance` field, a
validity window, a band, an embedding, or any value obtained from a
`ModelProvider`". A reconciler's *model* rung cannot reach an `EXTERNAL` target
under this ADR. That asymmetry is deliberate and it is what keeps ADR-0121 §3's
surviving half in force in the agreement direction as well as the contradiction one:
a model-judged statement is not a claim an observation is entitled to make against
the system that reported the fact, and that is as true of "these say the same thing"
as it is of "these cannot both be true."

**The purity condition is lifted from (ii) because on this pairing it costs and
buys nothing.** ADR-0159 §4's ground for it is honesty: a set holding both a
`RESTATES` and a `CONTRADICTS` member is one "in which the *stored records disagree
with each other*, and no ruling on this proposal resolves that". True — and (ii)'s
`ACCEPT` does not resolve it either. Work both branches through. The fold retires
nothing (ADR-0045 §4), installs nothing new, and lands byte-identical content on a
record that already carries it; the contradicting member stays live. Refusing the
fold installs a *third* live record saying exactly what the target says, leaves the
same contradicting member live, and — for a covered reading — leaves the target
absent, so ADR-0110 §5's close retires it. So blocking (ii) makes the store less
honest, not more, on the same set. §4(b) is unaffected in either branch: an eligible
(ii) member is labelled `RESTATES` whenever a reconciler ran, which blocks the
supersession arm exactly as ADR-0159 wrote it, so nothing is retired by this
lifting.

**Clause (ii) requires the same `reported_by`, so a fold between two integrations is
refused rather than left to fall out.** `Attestation.reported_by` is "the connected
source **instance** … stable across syncs, because ADR-0092 §6 leaves it as the only
durable handle the record keeps on where it came from", and the comparison is total
where clause (ii) reaches: an attestation "is present exactly when the band is
`ATTESTED`", and both records are `EXTERNAL`. Keying on it also puts presence and
absence on the same handle — ADR-0110 §3's condition 1 already selects absence
candidates by `reported_by` — so one reading's coverage and one reading's folds are
judged against the same identity rather than against two. Two integrations reporting
an entry that renders identically therefore land as two records, each present in its
own reader's reading, and nothing alternates. Whether that restriction should ever
be lifted is #1204's, and it is a deferral rather than an accident: this clause
decides the case, and decides it the conservative way.

**The precedence clause exists because the presence rule must not depend on a
ranking.** Without it, an `EXTERNAL` proposal whose set holds both its own identical
predecessor and a better-ranked `OBSERVED` member labelled `RESTATES` would fold
onto the observation, leave the predecessor absent, and close it — the very failure
this ADR repairs, reached by retrieval order instead of by source class. ADR-0110 §4
and ADR-0117 §1 both had to reason about ranking, and neither should have to again.
It also keeps the arm off the `ATTESTED`→`DERIVED` pairing whenever identity is
available, which is the conservative direction (§3).

### 2. Why ADR-0121 §3's ground does not reach this pairing, stated exactly

ADR-0121 §3's exclusion has one premise and one consequence:

- **Premise:** an imported record's `MemoryRecord.id` is the integrating system's
  idempotency key.
- **Consequence:** the next routine sync addresses that id, so a fold performed at
  it is overwritten and is therefore futile.

ADR-0092 §6 forbids the premise for every conforming producer, and does so as its own
ratified ruling rather than as a fact that might drift: the store's id is minted,
opaque to the source, and may not be the source's key "whether directly or
namespaced". Where the premise fails, the consequence does not follow, and no other
ground is offered for the agreement direction.

**What survives ADR-0121 §3 unchanged, and this ADR keeps all of it.** §3's ruling is
stated over the target source classes an agreeing restatement by a **user** may fold
onto, and that ruling is untouched: a `USER_ASSERTED` proposal still never folds onto
an import, `_AGREEMENT_FOLDABLE` does not gain a member, and §3's residue — the user
restating an import still falls through to the supersession arm and still mislabels
ADR-0120 §5's correction rate (#870) — is exactly as ADR-0121 §7 filed it.

**Nor does this ADR rule on whether ADR-0092 §5's reinforce-safe class should
widen.** §5 defines membership as "does not carry a foreign idempotency key" and
excludes `EXTERNAL` on the ground that it "still does not satisfy" it. Whether §6's
minting rule makes that characterisation stale is a real question about the *writer
floor* for a `USER_ASSERTED` proposal, and it is not this question: nothing here
needs the floor to move (§3). Filed as #1203 rather than half-ruled.

**A third-party attested producer with no stable key is exactly who this helps.**
The rejected alternative — give readers stable derived ids so a re-import lands at
the same id and ADR-0108 §2's install refusal takes over (§Alternatives) — helps only
a producer for whom a stable id can be computed at all, and ADR-0092 §6 forbids
computing one from the source's key or from content. A fold keyed on `agrees` asks
the source for nothing: it needs only that an unchanged entry render the same text
twice, which is a property of the producer's own `_render`, not of the integration.

### 3. What this does not widen, and the write it asks for is one the floor already permits

> **Normative.** This ADR opens no exception to `_refuse_unsafe_fold`, adds no
> member to the reinforce-safe class or the retirement class, and adds no member to
> the target class ADR-0121 §3 states for the asserted arm. Every write clause (ii)
> can ask for is one the writer floor permits today.

`_refuse_unsafe_fold`'s two clauses are keyed on sources this pairing does not
present. Clause 1 fires on a `USER_ASSERTED` **target**; clause 2 fires on a
`REINFORCE` whose **incoming** record is `USER_ASSERTED`. An `EXTERNAL` proposal
folding onto an `EXTERNAL` target trips neither, which is why the fold happens on
`main` today and why the three tests #1198 names pass there. ADR-0159 §5's last
clause — "Every write either arm above can ask for is one the writer floor already
permits" — stays true verbatim under this amendment.

**The implementation must not reach this by widening an existing constant**, and the
mistake has a name in the corpus. ADR-0092 §5 records it twice: a frozenset that
answers two questions "answers neither once the questions come apart", and widening
`_AGREEMENT_FOLDABLE` to admit `EXTERNAL` would re-admit a `USER_ASSERTED`
restatement folding at an imported id — the data loss ADR-0038 §2a reproduced and
ADR-0045 §5 kept refused by name. Clause (ii) is a *third* condition on a *different*
arm, conditioned on the proposal's own source, and it is held separately.

**Nothing is retired and nothing is demoted.** A `REINFORCE` retires no record at all
(ADR-0045 §4: the mechanism "lives entirely in the *applier*"; `SUPERSEDE` closes a
window, `REINFORCE` does not). Both records are `EXTERNAL`, so both are in the
`ATTESTED` band (`band_of`), so ADR-0103 §6's cross-band corroboration arm — stated
over an `ATTESTED` target reinforced by a `DERIVED` record — is not reached, and its
first clause is satisfied trivially: the survivor's evidence-strength is admissible
in the band it was already in. The `DERIVED`→`ATTESTED` fold ADR-0159 §12 says
`DefaultMemoryPolicy` no longer reaches on the observed path stays unreachable —
clause (ii) requires the proposal to be `EXTERNAL` — so #743's population is
unchanged and its contradiction is neither reopened nor resolved here.

### 4. The degraded path rules the same way, which is why the key is `agrees` and not the label

> **Normative.** ADR-0159 §6's degraded floor is the arm above with the policy
> supplying ADR-0121 §1's rung itself and every member otherwise unlabelled. With no
> reconciler injected, or with one whose every answer fails, an agreeing member is
> eligible under (i) where its source is `OBSERVED` or `INFERRED` — as §6 rules
> today — and eligible under (ii) on §1's conditions, and the arm rules on the
> result exactly as it does when a reconciler ran. Nothing else of §6 moves: it
> degrades to ADR-0121 §1's certain predicate plus `ACCEPT`, and never below it.

**§6's target class is §4(a)'s, and this clause says so rather than assuming it.**
§6's sentence — "rules `REINFORCE` onto a member that `agrees` under ADR-0121 §1" —
does not restate a target class, and read in isolation it would admit an agreeing
`EXTERNAL` member that §4(a) refuses on the reconciled path, so the degraded path
would fold where the reconciled one would not. §6's own heading forecloses that
reading: it degrades "to ADR-0121's floor, and never below it", and ADR-0121 §3's
floor is precisely where an `EXTERNAL` target is refused. §6 therefore delegates its
target class to §4(a), which is what makes moving §4(a) move both paths together —
by clause (ii) and by nothing else. §6 is **partially superseded** in that scope rather
than amended (§8): the delegation is why the scope is narrow, not a reason the
record is lighter, because §6's text as written names no class and an implementer
building only from it produces a different ruling after this ADR than before.

This is also the reason clause (ii) is keyed on `agrees` rather than on a `RESTATES`
label. A member that agrees is labelled `RESTATES` unconditionally by §3's first
rung whenever a reconciler ran, so on the reconciled path the two formulations pick
the same member. They come apart in the degraded case, where there are no labels at
all — and ADR-0159 §6 makes that case a **ratified deployment**, not a fallback: a
hub with no provider reachable, or one that "finds the queueing material" and takes
§6's floor deliberately. A presence rule that held only where a model provider was
configured would be a worse rule than the one ADR-0110 §4 ratified, and would fail
in the direction ADR-0117 §1 names — silently, invisibly, at the retained store's
expense.

### 5. What this restores, and that it is nothing more

The population clause (ii) admits is the population ADR-0110 §4 already ruled on.
§4 divides a re-appearing entry in two, and the division survives this ADR intact:

- **The unchanged entry folds** — it agrees, byte for byte after ADR-0121 §1's four
  transformations, and the two records name the same reporting source — so the fold
  lands at the target's id and the predecessor is present. That is §4's sentence,
  true again, and true whatever else the conflict set holds: the purity clause above
  is what keeps a third, contradicting member from re-opening the failure through
  the back door.
- **The rewritten entry does not fold** — "standup 9am" becoming "sprint planning,
  Thursday, room 4" does not agree — so it installs beside its predecessor, whose
  window the reading closes. That is §4's rewrite path, unchanged: "the predecessor
  genuinely stopped being true and the install carries the current text."

The two halves are now separated by exactly the predicate ADR-0110 §4's own converse
-hazard argument leans on — "identical text is the one case neither can miss" —
instead of by a similarity threshold that decided both cases at once. That is a
strictly better footing for §4's argument than the one it was written against, and
it is the only respect in which the restored behaviour differs from the ratified
one.

### 6. The conformance suite does not pin this pairing

> **Normative.** The shared `MemoryPolicy` conformance suite does not assert this
> pairing. ADR-0159 §8's last clause is unchanged and is not excepted: the suite
> asserts no relation-to-ruling mapping, and it asserts no source-class-to-ruling
> mapping either. The pairing is pinned as a `DefaultMemoryPolicy` test, and the
> property it exists for stays pinned end to end in
> `tests/memory/test_absence_reconciliation.py` and
> `tests/readers/test_calendar_absence_end_to_end.py`, which pass on `main` today
> and must pass again when ADR-0159's implementation lands.

> **Normative.** ADR-0159's implementing lane owes a `DefaultMemoryPolicy` test per
> branch §1's clauses introduce, landing with the implementation and not after it.
> Three of them are **not** reached by a repeat-read fixture, so passing the
> end-to-end tests above is not evidence that they hold: a set holding **both** an
> eligible (ii) member and a better-ranked (i) member, which must rule `REINFORCE`
> onto the (ii) member; a set holding an eligible (ii) member **and** a member
> labelled `CONTRADICTS`, which must still rule `REINFORCE`; and a set whose only
> `EXTERNAL` member agrees but carries a **different** `reported_by`, which must
> fall to (c).

> **Normative.** The same lane owes a **degraded-path** test — `relations` passed as
> `None` — for each ruling §8 records as changed against ADR-0159 §6's text: an
> `EXTERNAL` proposal agreeing with a same-`reported_by` `EXTERNAL` member, which
> must rule `REINFORCE`; the same with a different `reported_by`, which must rule
> `ACCEPT`; and an `OBSERVED` and an `INFERRED` proposal above `min_confidence`
> agreeing with an `EXTERNAL`-only conflict set, which must rule `ACCEPT`. An
> implementation that kept §6's unqualified "any agreeing member" would pass every
> reconciled-path test above and fail these.

**This ADR carries no test of its own, and that is the point of the clause above.**
It is prose, ratified ahead of the implementation under golden rule 5, so every
branch §1 opens is unpinned until PR #1197 lands. An implementation that ignored
`reported_by`, or kept the contradiction block over (ii), or took the first eligible
member by rank, would pass the two end-to-end suites named above and violate §1 —
which is exactly why the branches are enumerated here rather than left to whoever
writes them.

ADR-0040 §5's rule decides this and decides it against an exception: "a conformance
suite *is* the contract", so asserting a policy's ladder in it "would make one
policy's reasoning the contract". The rule this ADR states is `DefaultMemoryPolicy`'s
ladder — a *narrower* thing than the relation mapping §8 already declines, since it
also names a source class and a syntactic predicate — so if §8's clause holds, this
follows from it a fortiori.

**The consequence is stated rather than hidden.** `MemoryIngestor` takes rulings
from any injected `MemoryPolicy` (ADR-0040 §3), so a foreign policy that rules
`ACCEPT` here reproduces #1198's retirement loop and no conformance suite catches
it. That is already true of ADR-0121 §2's arm and of ADR-0159 §4 as ratified, and it
is the price ADR-0040 §5 knowingly pays. What bounds it is that ADR-0110 §4's
presence rule is stated over *what the ingest did*, not over what the policy must
rule — so the failure is visible in the reading's own result, and the end-to-end
tests named above are where it is caught.

### 7. Why this is a partial supersession and not an in-place amendment

ADR-0070 §1's test is "changes no decision", with the gloss "anything a reader would
act on differently" reading on *what was decided* rather than standing alone (its
2026-07-31 note). Applied here: a reader holding only ADR-0159 §4 builds a policy
that rules `ACCEPT` on an attested re-read of an unchanged entry; after this ADR they
build one that rules `REINFORCE`. That is the ruling itself, not a citation, a
cross-reference, or a mechanical consequence of a mechanism ADR-0159 does not own.

It is tempting to call it an amendment on the ground that §4's `EXTERNAL` paragraph
argues from a premise that is false on this tree, so the clause was never *decided*
for this pairing so much as swept into it. That reading is refused, and ADR-0070 §1's
own note refuses it: "A stale phrase whose correction *reverses a decision the ADR
made* is a supersession however it is labelled — ADR-0082 §1 says exactly that
('**The test controls, not the label**')." §4's clause is normative, explicit, and
argued; a mistaken ground does not make a ruling less of a ruling.

It is **partial** because one clause of §4 and the target set of §6 move, and
nothing else of either section does. ADR-0159's `Status` is a plain `Accepted`, so
it takes the leading-token form and a dated note (ADR-0070 §4, ADR-0082 §2), and
both land in this change — ADR-0070 §1's condition is that the
superseding ADR **exists**, and ADR-0082 §7's atomic-pair reading is satisfied because
the pair lands together.

### 8. What this records against earlier ADRs, under ADR-0082 §1

ADR-0082 §1's test, applied to each: would a reader holding only the earlier ADR now
act differently, or read one of its clauses more widely than it now holds?

**A record is owed on three.**

- **ADR-0159 §4 — partially superseded**, in the scope §1 names. Argued in §7.
- **ADR-0159 §6 — partially superseded**, in the scope of the members its degraded
  floor may name as a target. §6's normative clause is "rules `REINFORCE` onto a
  member that `agrees` under ADR-0121 §1", with no target class stated. Apply
  ADR-0070 §1's test to that text and not to a reading of it: an implementer
  building only from §6 folds onto an agreeing `EXTERNAL` member, and after this ADR
  rules `ACCEPT` on the same input. A changed ruling is a change to what was decided,
  so it takes a superseding ADR however narrow the scope, and ADR-0082 §1 says the
  test controls and not the label.

  **The scope is *not* narrowed to an `EXTERNAL` proposal, and that asymmetry with
  the §4 half is deliberate.** Two rulings change against §6's text, not one. The
  first is the cross-integration `EXTERNAL` fold above. The second is a proposal
  whose source is `OBSERVED` or `INFERRED` agreeing with an `EXTERNAL` member: §6's
  text folds, §1's clauses rule `ACCEPT` — eligible under neither limb, since (i)
  requires the *target* to be derived and (ii) requires the *proposal* to be
  external. That outcome is ADR-0159 §4(a)'s exclusion holding exactly as ratified,
  and this ADR neither widens nor narrows it; what is new is that §1 is the first
  place §6's target class is written down, so it is §1 an implementer now builds
  from. ADR-0082 §1 requires the record to cover every ruling that changes, so the
  §6 half of the scope is stated over every non-asserted proposal.

  **The delegation argument is why the scope is narrow, and it is not a reason to
  record less.** §4 above states the reading §6's own heading requires — it degrades
  "to ADR-0121's floor, and never below it", and ADR-0121 §3's floor is where an
  `EXTERNAL` target is refused, so a literal §6 would already have folded onto
  imports that ADR-0159 §4 refuses on the reconciled path. That inconsistency
  predates this ADR and is not a licence to leave a changed ruling unrecorded. What
  §6 **decided** is untouched and is relied on in §4: failure and absence degrade to
  ADR-0121 §1's certain predicate plus `ACCEPT`, as a ratified deployment rather
  than a fallback, and never below it. Only the target set moves, and it moves by
  clause (ii) and by nothing else — an agreeing `OBSERVED` or `INFERRED` member
  folds in the degraded case exactly as it does today.
- **ADR-0110 §4 — amended**, and the record ADR-0159 owed and did not write is
  written here for both changes at once. §4's sentence "The unchanged entry, which
  must not take that path, does not — ADR-0092 §6 puts it on `REINFORCE`, which
  folds at the target's id and marks it present" was written when *any* member above
  `conflict_threshold` folded. After ADR-0159 and this ADR it holds on a strictly
  narrower condition — the re-report must **agree** — so a reader holding only
  ADR-0110 would read it more widely than it now holds, and that fails §1's test.
  It is an **amendment** and not a supersession: what ADR-0110 §4 *decided* is the
  presence rule ("a record is present in `R` exactly when `R`'s ingest left it live
  at its own id") and the stored-nothing suspension, and neither moves by a word.
  The sentence at issue is the mechanical consequence of a fold rule ADR-0110 does
  not own and cites another ADR for — the case ADR-0070 §1's 2026-07-31 note puts on
  the amendment side by name. ADR-0110's `Status` carries a leading `Partially
  superseded by` token, so under ADR-0082 §2 the record is the appended dated note
  alone and no qualifier goes on the line.

**No record is owed on the rest**, and each is named because a reader may expect
otherwise.

- **ADR-0117 §1.** Its subject is a record whose window has not opened, and its
  three consequences are stated over "the next read's **identical** proposal" — the
  population `agrees` admits. Its bullet 3 chain ("finds no conflict … `ACCEPT` …
  installs at a freshly minted id") is true before and after, and more nearly
  vacuous after, since ADR-0159 §4(c) already rules `ACCEPT` on a set that is merely
  non-empty. Its report of ADR-0110 §4's converse-hazard argument stays an accurate
  report, and §5 above shows that argument standing on firmer ground. Nothing of §1
  becomes false or reads more widely, and §1 states no obligation in any case ("This
  section states no obligation").
- **ADR-0121 §1.** `agrees` is unchanged, is read here exactly as it stands, and is
  given no model-informed variant. This ADR reads the predicate; it does not touch
  it.
- **ADR-0121 §3.** Its ruling is stated over an agreeing restatement by a
  `USER_ASSERTED` proposal, and that population is disjoint from this arm's. Its
  argument is *cited* by ADR-0159 §4 and applied to a second population; declining
  that extension leaves §3's own sentence true word for word. §7's residue is
  untouched.
- **ADR-0092 §5 and §6.** §5's two named sets do not move and its
  `USER_ASSERTED`-proposal reasoning is untouched (§3 above). §6's ruling that the
  producer mints is relied on rather than changed, and its last paragraph
  ("`REINFORCE` takes the incoming attestation") is constructible on this pairing —
  both records are `ATTESTED`, so both carry an attestation and ADR-0092 §1's iff
  validator is satisfied either way. #743's contradiction is with the
  `DERIVED`→`ATTESTED` pairing, which this ADR leaves unreachable.
- **ADR-0092 §2 and §3, and ADR-0110 §3's condition 1.** `Attestation.reported_by`
  is read, not changed: §2's one-value-object shape and §3's stability are relied on
  as ratified, and clause (ii) keys a *presence* test on the same handle §3's
  condition 1 already keys the *absence* candidate selection on. Neither sentence
  becomes false and neither reads more widely — this is a stacked addition, recorded
  here and nowhere else (ADR-0082 §1).
- **ADR-0103 §6.** Its clause governs an `ATTESTED` target reinforced by a `DERIVED`
  record; clause (ii) is `ATTESTED` onto `ATTESTED`, which §6 leaves "as it stands".
  Its first clause is satisfied trivially. Neither is read more widely.
- **ADR-0045 §4 and §5.** §4's applier mechanism is untouched — a `REINFORCE`
  retires nothing and this ADR asks for no retirement. §5 clause 1 gains no
  exception (§3 above), and its "topical similarity may not retire a record the user
  gave us" is unaffected: a `USER_ASSERTED` member is never reached by this arm.
- **ADR-0050 §1 and ADR-0079 §3.** Both are about what a `SUPERSEDE` retires.
  ADR-0159 §5 narrowed them and this ADR touches neither §5 nor §4(b).
- **ADR-0108 §1 and §2.** The install refusal is not leaned on and is not relaxed:
  the fold means no install at a stored id is attempted, which is the same
  relationship §2 has had with every `REINFORCE`.
- **ADR-0040 §5.** Its "a conformance suite *is* the contract" is applied in §6
  above and reaches the same answer it has reached before. ADR-0159's own amendment
  of ADR-0040 §4 is untouched.
- **ADR-0159 §5, §8, §9, §11 and §12.** §5's exclusions and its last clause stay
  true (§3). §8's contract surface
  does not move and its conformance clause is applied rather than excepted (§6).
  §9 adds no metric key and this ADR adds none; the distribution shift §9 predicts is
  smaller by the attested re-read population, which is a change to a number and not
  to a definition. §11's clause-by-clause record stays correct on every ADR it
  names — this ADR supplies the two it did not reach. §12's dispositions of #868,
  #869, #871, #1169 and #743 are each untouched, and #743's is re-derived above.

### 9. What this ADR does not decide

- **Whether ADR-0092 §5's reinforce-safe class should widen** now that §6 forbids a
  foreign key. That is the writer floor for a `USER_ASSERTED` proposal, it is
  ADR-0121 §7's filed residue (#870) seen from the design side, and nothing here
  needs it. Filed as #1203.
- **Whether a fold between two different attested integrations should ever be
  permitted.** Clause (ii) refuses it, by requiring the same `reported_by`, and that
  refusal *is* a decision — the conservative one, taken because a survivor whose
  attestation alternated with whichever integration read last would also alternate
  the extent ADR-0110 §3's containment rule compares against. What is left open is
  the opposite ruling: that one fact two connected sources independently report is
  better held as one record with a composed attestation, the way ADR-0103 §6
  composes currency. That needs a decision about what an attestation identifies, it
  is unreachable until a second `EXTERNAL` producer exists, and it is filed as
  #1204.
- **The `MemoryPolicy` conformance suite's reach.** §6 declines this pairing; it does
  not reopen ADR-0159 §8's clause or ADR-0040 §5's rule.
- **Anything under `src/` or `tests/`.** The implementation is ADR-0159's lane
  (PR #1197), which this ADR unblocks and does not re-scope.
- **#736.** `FakeBeliefObserver` still derives its ids where `learning/observer.py`
  mints, so the fake still promises a `REINFORCE` its own id strategy prevents. That
  is the same "idempotency lives in the fold" design as this ADR's, one source class
  over, and it is genuinely open — the fold it needs is the `OBSERVED` one ADR-0159
  §4(a) already admits, so nothing here changes what #736 owes.

## Consequences

- **A scheduled reader stops retiring and re-installing its own beliefs.** That is
  the product consequence and the reason to act: record identity survives a re-read,
  ADR-0110 §4's presence rule works as ratified, and the retained store stops growing
  by its whole live set per cycle.
- **The fold that carries it is decided with no model.** The reconciler ADR-0159
  builds is not on this path, and a deployment with no provider reachable gets the
  same answer as one with a reconciler running — which is what makes the reconciler
  optional machinery rather than a dependency of the reader.
- **`decisions_reinforce` rises against ADR-0159's projection**, by the attested
  re-read population, which on a hub with a connected calendar is one fold per live
  entry per cycle and can dominate the counter. ADR-0159 §9's "not comparable across
  this change" label covers the same window and no new key is added; a reader
  comparing a post-0159 window against a post-0161 one should expect the attested
  share to move again.
- **`DefaultMemoryPolicy` gains a second, source-conditioned eligibility clause**,
  which is one more branch in the arm the pilot showed is easiest to get wrong. §1's
  clauses are stated so the branch is testable by enumeration: four source pairings,
  two label states, one predicate.
- **The corpus keeps one exclusion where it has a live reason and drops it where it
  does not.** ADR-0121 §3's refusal survives for the user's restatement, ADR-0092
  §5's floor is untouched, and what goes is the extension of an argument to a
  population its premise was never true of.
- **Revisit if a producer stops minting.** This ADR's whole ground is ADR-0092 §6.
  An ADR that let a producer adopt a source key or a content hash as
  `MemoryRecord.id` would restore ADR-0121 §3's premise for that producer, and
  clause (ii) would have to be re-argued rather than inherited.

## Alternatives considered

- **Leave ADR-0159 §4 as ratified and give `readers/` stable derived ids.** #1198's
  own alternative. A re-import would land at the same id and ADR-0108 §2's install
  refusal would take over, so no duplicate is created. Rejected: it needs its own
  ADR superseding ADR-0092 §6, whose ruling is that minting removes the aim and
  whose §Context is a resurrection reached exactly this way; it reaches a subsystem
  ADR-0159's lane cannot touch; it is defeated by any content change, where an
  `agrees` fold degrades correctly into ADR-0110 §4's rewrite path; and it helps
  only a producer for which a stable id can be computed at all.
- **Widen §4(a)'s target class to `EXTERNAL` unconditionally.** Simpler by one
  condition, and wrong. It would admit an `OBSERVED` proposal folding at an
  imported id on a *model-judged* restatement — a claim ADR-0121 §3's surviving half
  says an observation is not entitled to make against the system that reported the
  fact — and it would reopen the `DERIVED`→`ATTESTED` pairing #743 records a
  contradiction about. The `EXTERNAL`-proposal condition is what keeps the change to
  the population that has a producer standing behind it.
- **Key clause (ii) on a `RESTATES` label rather than on `agrees`.** Reads more like
  the rest of §4 and would need no extra term in the what-the-arm-reads clause.
  Rejected in §4: it admits the model rung onto an import, and it makes the presence
  rule depend on a reconciler being injected, so ADR-0159 §6's ratified
  no-provider deployment would silently lose it.
- **Rule it inside ADR-0159's implementation lane as a reading of §4.** Cheapest by
  far, and refused by CLAUDE.md ("do not relitigate them; propose a new ADR if you
  think one should change") and by ADR-0070 §1. §4's clause is explicit; reading it
  away in code would leave the corpus saying one thing and the tree doing another,
  which is the failure the ADR process exists to prevent.
- **Keep ADR-0159 §4(a)'s `CONTRADICTS` purity condition over clause (ii).** The
  literal reading of §4, and the one this ADR was drafted with. Refused in §1 on
  its own ground: on this pairing the block leaves the contradiction exactly as live
  as the fold does, and additionally duplicates a fact and retires a record under a
  covered reading. An honesty condition that makes the store less honest is not
  being applied, it is being copied.
- **Let clause (ii) fold across integrations, and file the consequence.** The
  drafted form, keyed on the source class alone. Refused in §1: it settles a real
  seam — whose attestation, and therefore whose extent, a shared record carries — as
  a by-product of a clause about something else. Requiring the same `reported_by`
  makes the same question a deferral (#1204) instead.
- **Amend ADR-0159 §4 in place.** Refused in §7: it changes what §4 decided.
