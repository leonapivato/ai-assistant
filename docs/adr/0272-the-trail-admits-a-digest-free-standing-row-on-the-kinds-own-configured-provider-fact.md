# 272. The trail admits a digest-free standing row on the kind's own configured-provider fact

- Status: Proposed
- Date: 2026-09-16
- **Partially supersedes**
  [ADR-0247](0247-the-configured-web-search-provider-is-the-destination-the-owner-chose-and-the-recipient-they-granted-and-the-call-budget-is-removed.md)
  — **§2's *eligibility conjunct* alone: the fact `AuditTrail.record` reads to admit a
  digest-free standing row.** §2 writes that conjunct as *"its binding's `closed_loop` is
  `True`"*, and states it three times in `closed_loop`'s own name — in the two-condition
  admission clause, in the eligibility-versus-discriminator clause, and in the clause
  excluding a stored row predating ADR-0193's implementation. §1 below replaces that one
  fact with **the binding's own kind's configured-provider fact**, exactly one of which
  must be carried. **Every other limb of §2 binds entire** — the pointer half, the digest
  discriminator, the narrowing of ADR-0193 §6's pairing clause to route (b), route (c)'s
  reachability on the same five conditions, its ordering before the grant seam, the
  trail-holds-no-configuration clause, the no-revalidation clause and the rendering
  clause — and so do §§1 and 3-16, **§4's `closed_loop` most of all**, which is untouched
  in its field, its type, its default, its carriage and its comparison, and stays the
  search kind's alone.
- **Partially supersedes**
  [ADR-0260](0260-a-forecast-read-is-its-own-seam-at-a-configured-provider-and-what-it-mints-carries-the-extent-that-makes-it-evidence.md)
  — **its header's `Everything else of ADR-0247 binds entire` sentence, in the words *"and
  its trail check"* alone.** That sentence is what makes §6's own ruling unrecordable: it
  creates the forecast kind and, in the same breath, keeps a trail check whose eligibility
  fact a forecast binding never carries. **Everything else of that sentence, and every
  other clause of ADR-0260, binds entire** — §6's widened route (c) and its three
  conjuncts, §7's *"bind, then rule, then record, then send"*, §11's `forecast_reach` with
  its restrictive default and its **`closed_loop` is untouched** clause, §12's three lanes
  and §13's arms.
- **This *is* a contract change, and this document is the ADR golden rule 5 requires for
  one** — ratified and merged as its own PR before the lane that implements it (ADR-0015).
  What it changes is **what `AuditTrail.record` accepts**, in one conjunct of one write-path
  check. What it moves is **no `core` type, no member, no signature and no
  `PROTOCOL_VERSION`**: `CarriedProvenance` and `EgressBinding` already carry both booleans
  (ADR-0260 §11, landed by that ADR's L1), no `Settings` value reaches the trail, and no
  stored row is revalidated, rewritten or re-derived. **And it moves no line of
  `core/protocols.py`**, which §3 states as a fact about that file read at `origin/main`
  `46403478` rather than as a posture, and conditions on a lane that finds otherwise.

## Context

### Where this comes from

**#2459, raised by ADR-0260's L2 lane (PR #2458) while writing §13's arms, and not fixable
inside it.** ADR-0260 §6 widens ADR-0247 §2's route (c) so that a forecast read at the
configured forecast provider is ruled `ALLOW` with `authorised_by` set to the binding's own
`account.reference` and `authorised_subject` unset. ADR-0247 §2 admits such a digest-free
standing row

> only where its binding's `closed_loop` is `True` **and** its `authorised_by` equals that
> binding's `account.reference`.

and ADR-0260 §11 keeps `closed_loop` meaning *"this deployment's own search"* and nothing
else, giving the forecast kind a sibling boolean instead. So the row ADR-0260 §6 mints
fails the first conjunct, and both implementations of the check refuse it —
`_check_configuration_authority` in `src/ai_assistant/permissions/audit.py` and the same
check in the canonical `FakeAuditTrail` in `src/ai_assistant/testing/permissions.py` —
with `InvalidAuthorisationError` and the words *"unless it is a closed-loop call naming its
own binding's connected account, which this is not (ADR-0247 §2)"*.

**The consequence is not a logged warning.** ADR-0260 §7 rules that the order inside one
servicing is *"bind, then rule, then record, then send"* and that *"[n]o channel is opened
before a recorded `ALLOW` exists"*; `orchestration/reads.py` records each servicing's
decision through the trail and treats a refused append as *the decision could not be
recorded*. So on the corpus as it stands **every** forecast read at the configured provider
would be ruled `ALLOW` and then dropped, and ADR-0260's L3 cannot land.

**No lane could close it, and that is why this document exists.** ADR-0260 §12's L2
paragraph enumerates what that lane owes and the trail is not among it, §12 adds *"[n]o lane
files or defers anything this ADR has not named"*, and ADR-0260's header states that *"§2's
route (c) and its trail check"* bind entire — so widening the conjunct in a lane would
contradict a ratified sentence, which is a decision (ADR-0070 §1).

**The same widening was proposed independently by the reviewer.** PR #2458's round-3
adversarial `blocker` reached the defect from the code rather than from the issue, and gave
as its Direction *"Extend the route-(c) audit check to admit the forecast eligibility fact
while rejecting neither/both-kind bindings and preserving the account-reference check."*
That lane waived the Direction — it may not take it — and recorded the convergence; §1 below
is that sentence, argued from the texts rather than adopted from the finding.

### The tree, read rather than assumed, at `origin/main` `46403478`

`_check_configuration_authority` takes `not binding.closed_loop or ruling.authorised_by !=
binding.account.reference` and raises; `FakeAuditTrail` carries the same two comparisons and
the same message, which is what makes the fake and the store one contract. Both are reached
from `_check_standing_shape`, after ADR-0254 §7's route-(d) branch, on the digest-free arm
alone. `EgressBinding.forecast_reach` exists, defaults `False`, and is written by
`orchestration` alone at the moment the request is built (ADR-0260 §11). The policy
already rules the forecast `ALLOW`: PR #2458 landed §6's widened route (c), each kind
compared against its own configured pair, with a binding carrying **both** facts at no
configured provider at all.

**Used here as given, and not rebuilt.** ADR-0247 §2's division of labour — *"`closed_loop`
is route (c)'s *eligibility* and the digest is its *discriminator*, and neither does the
other's work"* — with its companion, *"The trail asserts what it can see, and the policy
asserts the rest."* ADR-0254 §7's four-route partition, which tells the routes apart from
the row alone. ADR-0193 §6's pairing refusal, narrowed to route (b) by ADR-0247 §2.

## Decision

### 1. The eligibility fact is the kind's own, and exactly one of the two is carried

> **Normative.** **ADR-0247 §2's eligibility conjunct becomes *"the binding carries its
> kind's own configured-provider fact"*.** A non-resolving `ALLOW` carrying an
> `egress_binding` and an `authorised_by` with **no** `authorised_subject` is accepted
> **only** where **exactly one** of `binding.closed_loop` and `binding.forecast_reach` is
> `True` **and** its `authorised_by` equals that binding's `account.reference`. **Both facts
> are read from the decision** — no store read, no `Settings` read and no clock — and the
> population is the closed two-member set ADR-0260 §6 gives route (c), so nothing is
> admitted that route (c) does not cover. The refusal is `InvalidAuthorisationError` in
> every failing case.

> **Normative.** **Three of the four failing cases are refused exactly as `origin/main`
> refuses them, and the fourth is a refusal this decision adds.** A row carrying **neither**
> fact, and a row whose `authorised_by` is not its binding's `account.reference`, are
> refused today and are refused after this decision, with the same error type and the same
> reason. A row carrying **both** facts with a matching pointer is **admitted** today — the
> check reads `closed_loop` alone and `closed_loop` is `True` — and is **refused** after it.
> **That is the one behaviour this decision removes, and it is stated rather than glossed.**
> It is unreachable from a correct system, which is why it is safe to remove and not why it
> is permitted to go unsaid: ADR-0260 §11 writes each fact for exactly one kind, and §6 puts
> a binding asserting both at no configured provider, so no policy obeying either mints such
> a row. The lane §3 cuts pins it as a refusal for that reason.

> **Normative.** **A binding carrying *neither* fact is refused, and so is one carrying
> *both*.** Neither is the row ADR-0148 §3's third route covers: a binding asserting both
> kinds asserts a kind route (c)'s closed set does not contain, and admitting it would let
> one kind's authority be read off the other's. **The trail takes this itself rather than
> inheriting it**, and that is deliberate — the policy's own fail-closed arm for the
> both-fact binding (ADR-0260 §6, landed by PR #2458) makes the case unreachable from a
> correct policy, and ADR-0247 §2's *"[n]either component is offered the other's job"* is
> the reason the trail does not rely on that.

> **Normative.** **The pointer half and the digest discriminator are untouched, and neither
> takes on the eligibility's work.** `authorised_by` must still equal the binding's own
> `account.reference`, for `_check_authorisation`'s own stated reason — *"Without this the
> pointer is a string a policy could invent."* The digest still says which route a row
> claims, over the whole history and from the row alone, and ADR-0254 §7's four-route
> partition is unchanged in every limb: this decision changes **what makes a route-(c) row
> eligible**, never **which rows are route (c)**. A lane that discriminated by either
> eligibility fact, or admitted a digest-free row on the pointer alone, has breached
> ADR-0247 §2 exactly as before.

> **Normative.** **The trail still holds no configuration and is given none.** §1's
> account-and-origin comparison stays the policy's, taken where the configured values live;
> no `Settings` value, no configured connection reference and no configured origin reaches
> `permissions/audit.py` or the canonical fake, and a lane that handed one to either has
> breached ADR-0247 §2's clause forbidding it. What the trail takes is the row's internal
> consistency and **the kind**, which is all this decision widens.

### 2. Why §2's exclusion of a pre-ADR-0193 row survives unchanged

> **Normative.** **No stored row can be misclassified as route (c) by this widening, and
> the argument is ADR-0247 §2's own applied to the second fact.** §2 excludes ADR-0193
> §11's reserved digest-free pointer — *"a pointer written before this ADR's implementation
> validated any"* — on the ground that *"no row predating that implementation can carry
> `closed_loop` `True`"*, `closed_loop` having been added by ADR-0238, which lands after it.
> `forecast_reach` was added by ADR-0260 §11, later still, so **no row predating ADR-0193's
> implementation can carry it either**, and a row carrying neither fact is refused by §1
> above. ADR-0193 §11's three states, its non-distinguishing bar, its opaque-digest rule and
> its no-liveness rule bind entire, and this decision adds no surface obligation to any of
> them.

> **Normative.** **No stored row is revalidated, rewritten or re-derived, and no decoding
> changes.** These are write-path checks; a decision written before this ADR keeps its
> `authorised_by`, its digest and its recorded meaning. `forecast_reach` already exists on
> `CarriedProvenance` with a `False` default (ADR-0260 §11), so a record written before it
> decodes exactly as it does today and is refused on the digest-free arm exactly as it is
> today. **`PROTOCOL_VERSION` does not move** and no stored shape does.

> **Normative.** **`OriginUnrecordedBinding` and `CoverageUnrecordedBinding` stay refused by
> name.** ADR-0184 §7's and ADR-0233 §14's ended-epoch refusals are untouched: such a
> binding carries neither fact, so it never reaches this check, and no lane reads this
> section as making an unrecorded origin readable as a configured provider.

### 3. The one implementing lane, and what it owes

> **Normative.** **One lane, one PR, in `permissions/` and `ai_assistant.testing` plus the
> shared conformance suite.** It takes `_check_configuration_authority` in
> `src/ai_assistant/permissions/audit.py` and the same check in `FakeAuditTrail` in
> `src/ai_assistant/testing/permissions.py` to §1's conjunct, in one change and with the two
> messages staying identical, and corrects in that same change every docstring citing the
> rule it moved. **It touches no `wire` version, no store schema, no `Settings` field and no
> byte of `orchestration/`.**

> **Normative.** **It moves no line of `core/protocols.py`, because no line of that file
> states the rule §1 moves — and where one is found, the lane corrects it in the same
> change.** `AuditTrail.record`'s docstring states the **route-(b)** eight-check invariant
> and names neither `closed_loop`, nor route (c), nor the digest-free admission at all; it
> likewise names neither ADR-0247 §2's own narrowing of that invariant's scope nor ADR-0254
> §7's route-(d) checks, so its staleness **predates this decision and is not created by
> it**. That drift is filed as #2464 and is **not** absorbed by this lane, which is the
> triage rule for a pre-existing defect. The conditional half is ADR-0260 §12's
> correct-every-docstring clause binding here: a `core` docstring citing the moved rule is
> documentation of this decision, which golden rule 5's own sequence permits the lane to
> write because this ADR is merged ahead of it.

> **Normative.** **The arms ride in `tests/permissions/audit_trail_contract.py`, so that the
> store and the fake are held to one contract.** Four arms over a digest-free standing row
> whose pointer equals its binding's `account.reference`: a binding carrying
> `forecast_reach` alone is **recorded**; one carrying `closed_loop` alone is **recorded**,
> and that arm is the search regression, unchanged in what it asserts; one carrying
> **neither** fact is **refused**; one carrying **both** is **refused**.

> **Normative.** **The pointer half is pinned over *each* admitted fact, not over one of
> them.** A mismatched-pointer arm written on the search binding alone leaves an
> implementation that takes the pointer comparison inside the `closed_loop` branch passing
> every other arm while recording a forecast row on an `authorised_by` the policy invented —
> which is `_check_authorisation`'s own hazard reaching the route this decision widens. So
> the mismatch arm is **parameterised over both one-hot states**, or is written twice, and
> either shape discharges this clause. **Every refusal arm asserts the type and not the
> message text**, which is `InvalidAuthorisationError`.

> **Normative.** **ADR-0260's L3 is briefed after this lane merges, and not before.** L3 is
> the servicing, and §7's *"bind, then rule, then record, then send"* runs through the check
> this lane widens; briefing it first would put a lane in front of the record that makes its
> work recordable. Nothing else of ADR-0260 §12's ordering moves: L1 and L2 have landed, and
> this decision adds no fourth lane to that section.

### 4. Scope, and what this records against earlier ADRs

**Two records, each with ADR-0070 §1's test applied to the earlier ADR's own text, which is
what ADR-0082 §1 asks of an author. Both header edits ride in this PR while this ADR is
`Proposed`** — ADR-0082 §7's condition is that the superseding ADR *exists*, and the pair is
atomic here, so no reader meets a qualifier resolving to nothing. The ratification commit
flips one `Status` line and changes no other byte (ADR-0165 §2).

- **ADR-0247 §2's eligibility conjunct — partially superseded.** A reader holding only
  ADR-0247 would read *"only where its binding's `closed_loop` is `True`"* as the whole
  admission rule and would refuse ADR-0260 §6's own ruling. That is ADR-0070 §1's test
  coming out on the supersession side, and ADR-0070 §3's partial form is the sanctioned
  tool. Everything else of §2 is read over the substituted fact and is otherwise untouched.
- **ADR-0260's header sentence — partially superseded** in the words *"and its trail
  check"* alone. A reader holding only ADR-0260 would read §2's trail check as binding
  entire over the kind that ADR created, and would refuse the row §6 mints. The sentence
  becomes false of the world ADR-0260 itself made, which is the supersession side of the
  same test.

**Where the records are written.** ADR-0247's `Status` already carries the leading
`Partially superseded by` token, so this ADR's pair is **appended** to it and the record
lives in the appended dated note (ADR-0082 §2); **no earlier pair's scope text is
rewritten**, because a scope parenthesis is its own ADR's record of its own reach and the
corpus is append-only (ADR-0070 §1). ADR-0260's `Status` reads `Accepted` and takes the
leading token with this ADR's pair, its own `Partially supersedes` bullets untouched. No
mark is added to either document (ADR-0089 §5).

**The clauses a reader would expect to have moved, and which did not.** **ADR-0254's
`binds entire` enumeration** names *"the digest-free admission on `closed_loop` and pointer
equality"* among what that decision left standing — and it stays **true**, because its
subject is the reach of ADR-0254's own supersession and ADR-0254 indeed replaced nothing
there. ADR-0260's sentence is recorded and ADR-0254's is not, and the difference is the
test rather than the wording: ADR-0260 created the very kind whose row the sentence makes
unrecordable, where ADR-0254 created a route that carries a digest and says nothing about
forecasts. **ADR-0254 §7's route-(d) checks** are untouched entire — a route-(d) row carries
a digest and an `authorised_goal`, so it never reaches the digest-free arm, and *"[a] lane
that reused route (c)'s eligibility here has breached this clause"* binds exactly as
written. **ADR-0193 §6's pairing clause**, as ADR-0247 §2 narrowed it to route (b), and its
eight checks are untouched. **ADR-0238 §1's third clause and §6's closed-loop disjunct** are
untouched: this decision reads `closed_loop` and never writes or widens it. **ADR-0021 §5's
disclosure floor** is untouched; a route-(c) `ALLOW` still owes `authorised_by`.

### 5. Marking, review and ratification

This ADR is **marked** under ADR-0089: every clause a reader could disobey is a
`**Normative.**` block quote, and unmarked text is read to determine what a marked clause
*means*, supplying no obligation of its own (§3). Marking is forward-only and nothing
ratified is marked (§5).

**The required review set is adversarial *and* architecture** (ADR-0015 §1): this decides a
write-path invariant stated in two ratified contract ADRs and a canonical fake in
`ai_assistant.testing`, prose-only though the PR is. It is **reviewed while `Proposed`** and
ratified only after, and **no lane implements against any clause until it is merged**
(golden rule 5, ADR-0015 §5).

## Consequences

**What becomes easier.** ADR-0260 §6's ruling becomes recordable, so §7's sequence completes
and a forecast read at the configured provider is performed rather than ruled and dropped.
L3 becomes briefable. And the trail's assertion about route (c) is stated once, over the
kind, rather than over one kind's name — so the next kind route (c) admits moves this
conjunct by adding a fact to it and finds the argument of §2 already written for it.

**What becomes harder.** The trail now reads two booleans where it read one, and an
exactly-one rule is a shape a careless implementation states as an `or`. That is why §3's
arms pin the **both** case and the **neither** case as refusals rather than leaving them to
the policy, and why the two implementations move in one change.

**What would trigger revisiting this.** A third kind reaching route (c), which would make
the exactly-one rule an exactly-one-of-N rule and is where a carried *kind* starts to be
worth more than a set of sibling booleans — ADR-0260 §6's argument for a sibling boolean was
stated over two members, not ten. And any decision giving the trail a configuration read,
which this ADR forbids and ADR-0247 §2 forbade first.

Refs #2459, #2255.
