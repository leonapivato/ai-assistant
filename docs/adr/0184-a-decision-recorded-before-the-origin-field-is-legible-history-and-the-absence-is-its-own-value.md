# 184. A decision recorded before the origin field is legible history, and the absence is its own value

- Status: Proposed
- Date: 2026-08-23
- **Decides `core/types.py` surface and one `core/protocols.py` obligation.** One
  new model, one widened annotation on one existing field, and two behavioural
  clauses — one on `ActionPolicy`, one on `AuditTrail` — with no signature change on
  either Protocol. It adds no Protocol, no enum, no error class, no function, no
  property and no method. Golden rule 5 and ADR-0015 §5 put it in its own PR,
  ratified before anything implements against it.
- **Required review set: adversarial *and* architecture.** Compelled, not declared:
  `CONTRIBUTING.md` → "Stop when the required reviews are green" makes a change
  contract-surface when it is "the ADR deciding that surface", and §2 decides
  `core/types.py` while §5 and §7 state clauses on `core/protocols.py`.
- **Partially supersedes one clause, by a type.** ADR-0150 §1's first clause types
  `PermissionDecision.egress_binding` as `EgressBinding | None`; §2 below widens that
  one annotation and nothing else. §11 states the scope and argues why every other
  clause of ADR-0150 §1 — one field, that name, that default, `ActionRequest`'s own
  type, and "a binding is either whole or absent" — stands exactly as written.
- **Answers a question ADR-0181 declined by name.** Its dated note of 2026-08-23
  records that "how a *store* reads a row it cannot fully validate" is not ADR-0181's,
  and files it as #1451. That routing was right for a *decoding policy* and is
  insufficient for *this* row, because the answer needs a `core` value that does not
  exist — see the Context's third subsection. ADR-0181's ratified clauses move not at
  all; §11 records the amendment.
- **Refs:** #1465 (the gap this closes), #1427 (track:world, milestone 23), #1451
  (which this supersedes as the route to the fix and which closes against the
  implementation lane), #1443 (the lane that discovered it). **Filed by this lane:**
  none.

## Context

### What is actually on disk, read rather than assumed

`EgressBinding` is a **stored** member of `PermissionDecision`
(`PermissionDecision.egress_binding`), and `SqliteAuditTrail` persists a decision as
its pydantic JSON dump in a `data` column, rebuilding it on every read through
`PermissionDecision.model_validate_json` in `permissions/audit.py`'s `_decode`.
ADR-0181 §3 added `planned_with_external_content` to `EgressBinding` **required with
no default**. A row written before that field existed therefore no longer validates,
and `_decode` reports it:

```text
AuditError: the audit trail holds a record that no longer validates:
  1 validation error for PermissionDecision
  egress_binding.planned_with_external_content
    Field required [type=missing]
```

This is not hypothetical and not a race. #1465 records that the owner's hub holds
**two** such rows in `audit.db`'s `decisions` table, counted 2026-08-23. The blast
radius is exactly the egress rows: `egress_binding` is `EgressBinding | None` with a
`None` default, so a decision about a non-egress call is unaffected.

`SqliteAuditTrail` carries `meta("schema_version")` and a `_migrate`, but that
mechanism is an additive, column-presence `ALTER` — it evolves the *table*, not the
JSON payload inside `data`. Nothing versions the payload's shape, and this ADR does
not mint the thing that would (§9).

### The one reader that already answers, and the four that do not

PR #1443's lane, fenced out of `permissions/audit.py`, filed the case; the
follow-on lane answered it in exactly one place. `SqliteAuditTrail.pending_confirmation`
recognises the shape through `_is_origin_unrecorded` — a deliberately narrow
predicate matching a *single* `missing` error at `egress_binding.planned_with_external_content`
and nothing else — logs the condition `origin-unrecorded` and returns `None`. That
was the right place to answer it and the reasons are recorded in the method's own
docstring: it is "the one reader whose answer a caller rebuilds a park from", one
legacy row no longer takes every park down with it, and no false confirmation card is
composed.

The same docstring is explicit that the other four readers were left alone, and why:

> **A reader that only reads is unaffected**, and deliberately: `get`, `recent`,
> `export` and `resolution_of` still report such a row through `_decode`'s
> `AuditError` […] Serving them a binding-less decision to make them succeed would
> breach ADR-0150 §1 for the sake of a read.

That reasoning rules out the fix that was available then. It does not establish that
the four readers are *correct*, and the failure they carry is worse than one row's
worth, because **`recent` and `export` are all-or-nothing reads**. `_ordered_sync`
selects every matching row and `_decode` maps over the whole list, so one
unreadable row denies the user every other row in the trail. ADR-0021 §4 states what
that costs in terms: "`export` matches `MemoryStore.export` and `PlanStore.export`
and **discharges ADR-0004 §6's portability obligation for this store**". Two rows
currently defeat that obligation wholesale, on a store whose entire premise is that
the user can read what was decided on their behalf. `get` fails for the named row
alone, and it has exactly one production consumer today — `StepRunner._recorded` —
while `resolution_of`, `recent` and `export` have none in `src/` and are exercised by
the contract suite and the tests. The harm is therefore to the contract's own
disclosure and portability guarantees and to every surface that will render history,
rather than to a live caller this hour; it is stated that way rather than inflated.

### Why this is a `core` decision and not a patch in `permissions`

ADR-0181's dated note routes "how a store reads a row it cannot fully validate" to
`SqliteAuditTrail`, "as its neighbouring rule for a corrupted or downgraded row
already is — no ADR states that one either, and ADR-0049 §1 cites it as behaviour
established there rather than deciding it". That routing is correct for the class it
names: whether an unreadable row raises, and with what message, is a decoding policy
the module owns.

It does not reach this row, for one reason. The module has no vocabulary in which to
hand such a row back. Every `AuditTrail` read is annotated `PermissionDecision`, that
type lives in `core/types.py`, and a decision *is* the ruling bound to what it was
ruled on (ADR-0021 §1). The three answers `permissions` could give on its own are
each closed:

- **`egress_binding=None`.** Forbidden. ADR-0150 §1's second clause makes `None` mean
  "the request is not an egress call", so a decision projected without its binding
  would state that a call with an account and a recipient had neither.
- **A supplied `planned_with_external_content`.** Forbidden twice. ADR-0181 §3 makes
  the field required with no default in terms, and §4's second clause forbids a seam
  inventing it "where a caller did not supply it" — which rules out `False` and `True`
  alike, as ADR-0181's own note restates.
- **A type minted in `permissions`.** Forbidden by golden rule 1 and by
  `CONTRIBUTING.md`: public data that crosses a subsystem boundary is a pydantic
  model in `core/types.py`, and this value crosses from `permissions` to whatever
  reads the trail.

So the remedy is a `core` surface, which is golden rule 5's territory and takes a
ratified ADR ahead of its implementation. That is what this document is. It answers
one question ADR-0181 declined; it does not disturb the routing for the class ADR-0181
was actually talking about, and §5's second clause keeps every *other* unreadable row
exactly where `_decode` already puts it.

### The wall: fabricating nothing while representing something

The row records four facts and is silent about a fifth. Every candidate design was
weighed against one test — that it **fabricates nothing** — and a second that is
easy to forget: that it **discards nothing the row does record**. A marker saying
only "this row is old" passes the first and fails the second, throwing away the
account, the recipients and the payload description the user is entitled to read. The
answer has to be a value that says exactly what the row says: these four facts, and
no fifth.

## Decision

We will give the pre-ADR-0181 egress row a `core` value of its own, discriminated
from an ordinary binding by the shape of what was stored rather than by a date, a
version or a flag; return it from the trail's history readers; write nothing, ever, in
either direction; and keep every route by which such a decision could authorise a
transmission closed.

### 1. The shape is the condition, and it is recognised by nothing else

> **Normative.** The rows this ADR represents are exactly those whose stored
> `egress_binding` is a JSON object carrying every member `EgressBinding` requires
> **except** `planned_with_external_content`, each satisfying its own constraint, and
> carrying no member `EgressBinding` does not declare. A row failing in any other way,
> in any additional way, or at any other position is a corrupted or downgraded store
> exactly as it is today.

> **Normative.** No lane recognises such a row by `decided_at`, by a date range, by
> `meta("schema_version")`, by a table column, by a deployment identifier or by any
> other fact about *when* or *by what* it was written. The shape of the stored value is
> the whole of the condition.

The narrowness is the point, and it is inherited rather than invented:
`_is_origin_unrecorded`'s own docstring already fixes it — "a row with a second
fault, a fault anywhere else, or a fault of any other type is a corrupted or
downgraded database exactly as before". §3 makes that narrowness structural instead
of a predicate over a `ValidationError`'s shape, which is strictly the stronger form
of the same rule.

Recognising by date would be worse than merely fragile. The trail is append-only and
ordered but carries no record of which code wrote a row, an installation may upgrade
at any instant, and a restored backup or a copied data directory carries rows whose
`decided_at` says nothing about the schema they were written under. The stored value
is the only witness that cannot lie about itself.

### 2. `core` gains one value, `EgressBinding` gains nothing, and `None` keeps its meaning

> **Normative.** `core/types.py` gains `OriginUnrecordedBinding`: a frozen model with
> `extra="forbid"` carrying `spans`, `account` and `transport_endpoint` — every member
> `EgressBinding` carries **but** `planned_with_external_content` — with the same types,
> each required with no default, and satisfying every structural invariant
> `EgressBinding` enforces over the same members.

> **Normative.** The shared members, their validators and the derived
> `canonical_destination_set` are declared **once**, on a private base both models
> inherit; neither model restates a member, a validator or a derivation the other
> declares. A second declaration of the same facts is the "second shape that must
> agree" failure ADR-0150 is named after, arriving one level down.

> **Normative.** `EgressBinding` is unchanged. `planned_with_external_content` stays
> `bool`, required, with no default; no member is added to it, removed from it or
> re-typed; and every ADR-0181 §10 invariant over a binding that has the field holds
> for that model exactly as ratified.

> **Normative.** `ActionRequest.egress_binding` stays `EgressBinding | None`, and its
> `_detached_binding` validator is untouched. No request carries an
> `OriginUnrecordedBinding`, and no lane widens that field on the strength of this ADR.

> **Normative.** `PermissionDecision.egress_binding` becomes
> `EgressBinding | OriginUnrecordedBinding | None`, still one field, still named
> `egress_binding`, still defaulting to `None`. `None` continues to mean exactly what
> ADR-0150 §1's second clause makes it mean — the request is not an egress call — and
> no lane uses it to mean anything else, this row included.

> **Normative.** Nothing else is minted. No enum, no error class, no function, no
> property, no method, no `Literal` tag and no field is added to `EgressSpan`,
> `ConfirmationEgress`, `Confirmation`, `ActionRequest` or `PermissionDecision` by this
> ADR beyond the one annotation named above. A consumer that must tell the two apart
> narrows with `isinstance`, and no lane adds a convenience for it.

**Two siblings over a shared base is the house shape, in this same file.**
`_SeverityScale` is a private base with three public members (`RiskLevel`,
`Reversibility`, `PermissionOutcome`); `MemoryBase` has four; `ContextFacet` has
`CalendarFacet` and `EmailFacet`. Sharing the declaration is what makes "the same
three facts" true by construction rather than by review, which matters here more than
it usually does: `canonical_destination_set` is what a surface renders, and a history
row whose derived set were computed by a second copy of that derivation could disagree
with the one the user was shown when the ruling was made.

**The inheritance runs this way round and not the other.** Making `EgressBinding`
inherit from `OriginUnrecordedBinding` would mint one name instead of two and is
wrong twice: it reads as "a binding with a recorded origin is a kind of binding whose
origin was never recorded", and — the part that would actually bite — it makes
`isinstance(binding, OriginUnrecordedBinding)` answer `True` for every live binding,
so the one narrowing every consumer performs would silently misfire.

**`OriginUnrecordedBinding` carries the recorded facts rather than standing for their
absence**, which is the Context's second test. The user reading their exported trail
sees the connected account, every occurrence with both supplied and canonical forms,
the payload description and the transport endpoint — everything the row actually
holds — and learns exactly one thing more, that the origin of this call was never
recorded. A marker type would have thrown the rest away to say so.

### 3. The discrimination is structural, total and mutually exclusive

> **Normative.** Both models forbid unknown members (`extra="forbid"`), which is what
> makes the union total and mutually exclusive with no discriminator field: a stored
> object carrying `planned_with_external_content` validates as `EgressBinding` and as
> nothing else, and one without it validates as `OriginUnrecordedBinding` and as nothing
> else. No lane adds a tag, a version key, a `Field(discriminator=...)` or a
> `Literal` member to either model to do a job `extra="forbid"` already does.

**Verified in this tree rather than reasoned about.** Against the pinned pydantic
(2.13.4), over a base with `extra="forbid"` and two siblings differing by one required
`bool`, validating through a `TypeAdapter` of the union:

| stored object | result |
| --- | --- |
| every member, including the flag | the flagged model |
| every member but the flag | the flagless model |
| a member of the wrong type, flag absent | raises |
| a member the models do not declare | raises |
| `null` | `None` |

The third and fourth rows are the ones that matter for §1: a row that is *both* missing
the flag *and* faulty elsewhere satisfies neither member and still raises, so the
tolerance this ADR adds is exactly one shape wide. That is the property
`_is_origin_unrecorded` bought with a hand-written predicate over `exc.errors()`, now
carried by the type system instead.

### 4. Nothing is written, in either direction

> **Normative.** No migration rewrites, backfills, annotates, versions, re-keys or
> deletes such a row, and no lane adds one. The representation is **read-side**: the
> bytes in the `data` column are not touched by this decision.

> **Normative.** `AuditTrail.record` refuses a decision whose `egress_binding` is an
> `OriginUnrecordedBinding`, with the trail's existing refusal for a decision that is
> not a valid record (`AuditError`) and no new error class. The shape is only ever
> **read** out of a store, never minted into one.

> **Normative.** `PermissionDecision.from_request` cannot produce one and gains no
> route to. It transcribes the binding from `ActionRequest.egress_binding`, which §2
> leaves narrow, so the origin-unrecorded shape is unreachable from every live path by
> construction rather than by a check.

**A migration is forbidden on two independent grounds and either would be enough.**
It would have to supply the value, which ADR-0181 §3 and §4 forbid — the whole of
#1451's analysis, and ADR-0181's own note restates it. And it would rewrite an
appended record, which is the one property the trail exists to deny: ADR-0021 §4 gives
the trail no `update` at all, and the `AuditTrail` Protocol states the principle as
"the user may burn the book; nobody may tear out a page". A migration that only
*annotated* the row — adding a marker key beside the members — is the same violation
with a friendlier name, and is refused for the same reason.

**Refusing at `record` costs nothing and closes the only route left.** Once the union
exists, a caller bypassing `from_request` could construct a decision carrying the
legacy shape and append it, minting a new row in an epoch that has ended — a
fabrication of history rather than of a value, and the harder one to notice later.
`record` is where the trail already enforces what a model cannot see for itself (the
resolution invariant, the authorisation pointer, the ordering rule), for the reason
ADR-0021 §4 gives: it is the boundary where the whole record is in hand. This is one
more clause of exactly that kind. It does not contradict the two rows that exist: they
were written when this shape *was* the current shape, which is the entire point of
representing them rather than accepting them.

**Wholesale erasure stays the only sanctioned removal.** ADR-0021 §4's `clear` is
available to the user and to nobody else, and this ADR neither recommends nor
requires it. A user who would rather not carry two unanswerable rows may burn the
book; no lane burns it for them, and no lane offers to remove the two rows alone.

### 5. What the five readers answer

> **Normative.** `get`, `recent`, `export` and `resolution_of` return a decision whose
> `egress_binding` is an `OriginUnrecordedBinding` as history, rather than raising. A
> `recent` or an `export` over a trail holding such a row returns it **together with**
> every other row, which is the all-or-nothing failure this closes.

> **Normative.** `pending_confirmation` still answers `None` for such a binding. The
> `origin-unrecorded` refusal stands in name and in effect: nothing is written, the step
> stays durably `AWAITING_APPROVAL` with its `CONFIRM` unresolved and its row intact,
> the two callers refuse by their own existing names, and one such park does not hide
> another binding's live one. Nothing in this ADR makes such a park resumable.

> **Normative.** What changes for `pending_confirmation` is only how the case is
> **detected** — on the decoded value's type rather than on the shape of a
> `ValidationError` — and the module keeps the `ORIGIN_UNRECORDED` condition name a
> reader meets in the log.

> **Normative.** Every other row that fails to validate is reported exactly as it is
> today, through `_decode`'s `AuditError`. This ADR widens what the trail tolerates by
> the one shape §1 names and by nothing else.

> **Normative.** `resolution_of` returns such a row as history and as nothing more. No
> consumer treats a decision a reader returned as an authorisation without
> `PermissionDecision.authorises`, which §6 makes answer `False` for it.

**The asymmetry between `pending_confirmation` and the other four is not an
inconsistency, it is the distinction the whole design turns on.** A park is a question
put to the user, and answering it composes a `Confirmation` the user acts on; a
history read states what was recorded. There is no answerable question in an
unanswerable park, so `pending_confirmation` hands back nothing — and there is a
perfectly legible record behind it, so the readers hand it back. `pending_confirmation`'s
docstring already draws this line ("the damage a legacy row does is to the **park**
path, and that is where it is answered"); this ADR keeps the line exactly where that
lane put it and supplies the value the other half was missing.

**The obligation is stated on the `AuditTrail` Protocol and pinned where it can be.**
The decode behaviour itself is a property of a store that persists a serialised payload
and rebuilds it, and the canonical fake in `ai_assistant.testing` holds objects rather
than bytes, so no shared conformance case can seed it — ADR-0049 §5's reasoning for
putting a persistence-model-specific guarantee in the implementation's own tests
applies unchanged. `record`'s refusal is a different matter: a test can construct such
a decision now that the type exists, so that clause **does** belong in the shared suite
and every implementation owes it. §10 splits the tests accordingly.

### 6. `authorises` answers `False`, and gains no conjunct

> **Normative.** `PermissionDecision.authorises` answers `False` for every decision
> whose `egress_binding` is an `OriginUnrecordedBinding`, against every request. No
> conjunct is added for it, no special case is written, and no lane compares the
> binding's members separately or exempts any of them from the comparison.

The answer falls out of what is already ratified, which is why no code is owed. ADR-0150
§9 and ADR-0181 §3's fourth clause make the binding compared **whole and by value**;
pydantic's equality is per class, so a model of one class never equals a model of
another whatever its members hold, and `None` equals neither. Verified in this tree
alongside §3's table: the comparison answers `False` in both directions and for `None`
on either side. ADR-0181's own note reaches the same place from the other direction —
"§3's fourth clause makes `PermissionDecision.authorises` answer `False` for it in any
case" — and this clause records that the widening does not disturb it.

Two grounds meeting at the same answer is worth stating rather than economising on: a
future lane that changed the comparison would have to break both to make such a
decision authorise anything.

### 7. The floor on `ActionPolicy`, and the one member it binds

> **Normative.** `ActionPolicy.resolve` returns no `ALLOW` on a `confirmed` whose
> `egress_binding` is an `OriginUnrecordedBinding`, whatever `approved` says. The origin
> of such a call cannot be established at all, and ADR-0181 §5's second clause leaves no
> route by which any authorisation covers it.

> **Normative.** `ActionPolicy.decide` gains no clause for this case, because §2 leaves
> `ActionRequest.egress_binding` narrow and the case is therefore unconstructable at that
> member. No lane adds one, and no lane widens the request's field in order to need one.

> **Normative.** The `resolve` clause is stated on the `ActionPolicy` Protocol and added
> to `ActionPolicyContract` in the same change as the type. Neither Protocol's signatures
> move.

**A floor rather than a route that exists.** §5 makes `pending_confirmation` refuse such
a row, so nothing in the tree today hands one to `resolve`. The clause is written anyway,
and ADR-0021 §5's "fail-closed twice over" is the precedent: the value of a floor is that
it holds when a route appears, and this one is cheap because it is checkable on any
implementation without knowing its rules. It is the mirror of ADR-0181 §5's third clause,
which binds `decide` and `resolve` separately "each over the facts its own member
receives"; here only one member can receive the fact, so only one is bound.

The shape is ADR-0106 §10's and ADR-0181 §10's second clause: a behavioural obligation on
an existing Protocol member, stated in the docstring, asserted in the conformance suite,
with no signature change.

### 8. No wire move, and no confirmation shape for an unrecorded origin

> **Normative.** `PROTOCOL_VERSION` does not move for this decision, and nothing under
> `wire/` changes. ADR-0124 §9's limb does not fire.

> **Normative.** `ConfirmationEgress` is untouched, and no lane mints an
> origin-unrecorded confirmation shape, adds a nullable member to `ConfirmationEgress`,
> or renders a confirmation for such a row.

> **Normative.** `EgressBinder.rebind` is untouched and never receives an
> `OriginUnrecordedBinding`. ADR-0152 §7 and ADR-0181 §3's fifth clause stand as written.

> **Normative.** Every site that reads a *decision's* `egress_binding` narrows the union
> and refuses the origin-unrecorded case rather than assuming it away, whatever the
> reachability argument says. §10 names them.

**The wire claim is checked, not assumed.** ADR-0124 §9's second limb fires on "a change
to a wire-carried `core` type that makes a value one peer emits invalid for the other".
`PermissionDecision` is named nowhere under `wire/` and is returned by no promoted method
— what crosses is `Confirmation`, carrying `ConfirmationEgress`, which ADR-0178 §5 builds
from the recorded decision at two assembly sites. Both sites are reached only through
`pending_confirmation`, which §5 keeps refusing such a row, so no confirmation is ever
assembled from one and the emitted shape does not change. `PROTOCOL_VERSION` stays at
**11**, where ADR-0181's implementation left it.

**And a `ConfirmationEgress` for such a row is not merely unreachable, it is refused.**
That model's `planned_with_external_content` is required with no default (ADR-0181 §3's
third clause), so composing one for a row that never recorded the value would demand the
fabrication this whole ADR exists to avoid — at the surface where the user is being asked
to approve something, which is the worst place in the system to invent a fact. The
absence is answered by not asking the question, which is what §5 preserves.

### 9. Exactly one epoch, and what a second one would owe

> **Normative.** This ADR authorises **exactly one** such sibling, for exactly one epoch:
> the rows written between `egress_binding`'s arrival on `PermissionDecision` (ADR-0150 §1,
> as implemented) and `planned_with_external_content`'s (ADR-0181 §3, as implemented). No
> lane adds a second sibling to this union, or a sibling to any other model, on the
> strength of this ADR.

> **Normative.** An ADR that adds a further member to `EgressBinding` — or to any other
> `core` model the audit trail stores — **required with no default** decides that field's
> own history representation in its own text, before its implementation lands. It may cite
> this ADR as a precedent for the shape; it may not cite it as a licence, and it does not
> inherit this ADR's answer by default.

The mechanism generalises and the *type* deliberately does not. `OriginUnrecordedBinding`
names one field's absence and no other, and a reader meeting it learns something specific.
A general "binding from some earlier schema" would learn nothing, and accumulating one
sibling per epoch is a shape that degrades: three siblings is six pairwise
discriminations to reason about and a union every consumer must exhaust.

**Deferred, with its trigger: a stored payload version for the trail's `data` column.**
The trail versions its *table* and nothing versions the payload, which is precisely why
this question had to be answered by shape. A version key would answer it by declaration
instead, and would make the next epoch cheap. It is not minted here because it is
machinery for a problem that has occurred once, over two rows, and because adding it now
would itself be a write to every future row for a benefit nothing has yet needed.
**It fires with the second such epoch** — the next member added required-with-no-default
to a model the trail stores — and the ADR adding that member chooses between a second
sibling and a version, in its own text, with two data points instead of one.

### 10. What the implementing lane owes

> **Normative.** The paired lane is the `core` change together with its primary
> production implementation in `permissions/audit.py` (ADR-0137 §2). `core` gains the
> value; `permissions` is the only subsystem whose behaviour changes, and every other
> site named below is adaptation in ADR-0137 §1's sense and rides in the same lane,
> which §1's second clause permits without limit.

> **Normative.** The lane ships construction tests: `OriginUnrecordedBinding` refuses
> `planned_with_external_content` as an unknown member, and refuses a missing `spans`,
> `account` or `transport_endpoint`; `EgressBinding` still refuses construction with
> `planned_with_external_content` omitted; and each model's `model_fields` roster is
> asserted, so a member added to either without the other is caught.

> **Normative.** The lane ships the discrimination tests of §3 **over a real
> `SqliteAuditTrail`**, seeding the row by writing the JSON into the `data` column
> directly, because §4 makes the row unproducible through `record`: the stored decision
> with the key decodes carrying an `EgressBinding`; the same JSON with exactly that key
> removed decodes carrying an `OriginUnrecordedBinding`; and the same JSON with that key
> removed **and** a second fault elsewhere still raises `AuditError`. The third case is
> the one that fails an implementation which widened the tolerance rather than shaping it.

> **Normative.** The lane ships reader tests over a trail holding **one** such row among
> **several** ordinary ones: `recent` and `export` each return every row including it;
> `get` returns it by id; `resolution_of` returns a legacy resolution by its binding. A
> test exercising a trail whose only row is the legacy one passes an implementation that
> still fails the whole list, and does not satisfy this clause.

> **Normative.** The lane ships a round-trip test that a returned decision's
> `model_dump()` carries **no** `planned_with_external_content` key anywhere under
> `egress_binding` — nothing is fabricated on the way out, and an export is a faithful copy
> of what the row says.

> **Normative.** The lane ships `pending_confirmation` tests that survive the change: such
> a park still answers `None`, still logs `origin-unrecorded`, writes nothing, leaves the
> row and the step intact, and does not suppress a live park on a different binding. These
> are #1443's follow-on lane's tests, re-pointed at the structural check, and a lane that
> deletes them has removed the refusal rather than reimplemented it.

> **Normative.** The lane ships an `authorises` test: a decision carrying an
> `OriginUnrecordedBinding` against a request whose `EgressBinding` carries the same
> `spans`, `account` and `transport_endpoint` answers `False` — asserted for a request
> carrying `True` **and** for one carrying `False`, so neither value is the reason.

> **Normative.** The lane adds `record`'s refusal to `AuditTrailContract`, so the canonical
> fake owes it too, and adds §7's `resolve` case to `ActionPolicyContract` with its
> boundary: an ordinary binding with `approved` true is still judged on the ordinary path.

> **Normative.** The lane ships a test pinning `PROTOCOL_VERSION == 11`, unmoved.

- **The narrowing sites**, each of which must narrow and refuse rather than assume:
  `orchestration/engine.py`'s confirmation-egress assembly (`recorded.egress_binding`),
  `orchestration/runner.py`'s `_rebound` call site (`confirmed.egress_binding`),
  `permissions/policy.py`'s `resolve`, and the canonical fake policy in
  `testing/permissions.py`. `mypy --strict` will demand each of them; the clause above is
  what decides *how* each answers.
- **`_is_origin_unrecorded` retires** with the `ValidationError` shape it matched.
  `ORIGIN_UNRECORDED` — the condition name — stays, because a name in a log is what a
  reader meets.
- **#1451 closes against this lane**, and #1465 against it too. #1451 asked whether the
  consequence "may want a line in an ADR"; §5 and §9 are that line, and they answer it
  the way the issue's own analysis pointed rather than by relaxing anything.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

**ADR-0150 is partially superseded, in one clause, by a type.** §1's first clause rules
that `PermissionDecision` gains exactly one field for the binding, "named `egress_binding`",
"typed `EgressBinding | None`", "defaulting to `None`". §2 above changes the type of that
one field on that one model and nothing else, so a reader holding only ADR-0150 would read
the annotation and act differently — ADR-0070 §1's test for a supersession rather than an
amendment. The scope is stated on ADR-0150's Status line beside ADR-0178's existing entry,
and in a dated header note, as ADR-0181 recorded its two count-supersessions.

**Everything else in ADR-0150 §1 stands whole, and each is worth naming because each could
be misread as breached.**

- *Exactly one field.* Still one. This ADR widens an annotation; it does not add a second
  field, and §2's clause forbids one — which is the clause ADR-0150 §1 wrote against
  ("no lane spreads the binding's facts across several fields of either model").
- *That name, that default.* Both unchanged.
- *`ActionRequest`'s field.* Untouched, including its `_detached_binding` validator.
- *`None` means the request is not an egress call.* Unchanged and load-bearing: it is the
  reason this ADR exists, since it is what forbids the cheap projection.
- *A binding is either whole or absent; there is no partially populated `EgressBinding`.*
  Unchanged. An `OriginUnrecordedBinding` is not a partially populated `EgressBinding` — it
  is a different model, every one of whose members is required, and the fifteen partial
  states ADR-0150 §1 refuses remain unexpressible.
- *`authorises` gains one conjunct rather than four.* Still one; §6 adds none.

**ADR-0181 is amended, not superseded, and no clause of it moves.** Its dated note of
2026-08-23 states that "how a *store* reads a row it cannot fully validate" is not its to
decide and files it as #1451. This ADR answers that question for the one shape §1 names,
and shows in the Context's third subsection why the answer needed a `core` value rather
than a decoding policy. A reader holding only ADR-0181 would look for the representation
and not find it, which is ADR-0082 §1's test for an owed record; but that reader would act
**identically** on every clause ADR-0181 states — §3's required-no-default and its four
model clauses, §4's discard-not-merge, §5's two ruling points, §10's test obligations — so
under ADR-0070 §1 it is an amendment. A dated header note is appended to ADR-0181 in this
change.

**Both records are written in this change and take effect on merge, which is the only
sequence this project's mechanism admits.** ADR-0165 §5 constrains the ratifying commit
to a single changed line — one ADR's `- Status: Proposed` becoming `- Status: Accepted`
and no other byte — so a record on another ADR cannot ride in it, and `just ready`
refuses while an ADR the PR touches still reads `Proposed`, so there is no
post-ratification change in the workflow to defer a record to either. Every cross-ADR
record in this corpus is therefore written while its deciding ADR still reads
`Proposed`: ADR-0181's authoring commit wrote its records on ADR-0178, ADR-0152,
ADR-0150, ADR-0106 and ADR-0154 — ADR-0178's Status line named ADR-0181 in that same
commit — and its ratifying commit came afterwards. ADR-0070 §1 permits a Status-line
edit "recording a supersession that has landed", and its stated condition is that the
superseding ADR *exists* rather than that it was ratified in an earlier change; the
edit it forbids is "flipping a live decision to `Superseded` with no such ADR", which
is not this. Nothing intermediate is published: a reader meets ADR-0150's Status line
and this ADR's `Accepted` status at the same instant, and ADR-0015 §5's rule — that
this ADR is ratified before anything **implements** against it — is untouched, since
the implementation lane is briefed after this merges.

**No record is owed on ADR-0021, ADR-0044, ADR-0049, ADR-0148, ADR-0152 or ADR-0178.**
ADR-0021 §4's append-only rule is *used* here and not narrowed — §4 above obeys it rather
than carving an exception. ADR-0049 §1's observation that the corrupted-row rule is
behaviour established in the module stays true: §5 leaves every other unreadable row exactly
where `_decode` puts it. ADR-0148 §6's transcription, ADR-0152 §7's `rebind` and ADR-0178's
`ConfirmationEgress` are each untouched by §8's clauses. ADR-0082 §1 forecloses the
book-keeping objection: a record may be demanded only by naming a sentence this change
falsifies, and none of these carries one.

## Consequences

**What becomes easier.** The user can export their audit trail again, and read the two rows
that currently deny them the rest. Every surface that will render decision history — the
gateway's audit view, a CLI listing, whatever #1427's later milestones build — has a value
to render for these rows instead of an exception to special-case, and it renders the account,
the recipients and the payload description that were recorded rather than a blank. The
narrowness that `_is_origin_unrecorded` maintained by hand becomes a property of the types,
so a lane cannot widen the tolerance by loosening a predicate. And the next lane that must
add a required member to a stored `core` model has a worked precedent and an explicit
instruction (§9) to decide rather than inherit.

**What becomes harder.** `PermissionDecision.egress_binding` is a three-member union, so
every consumer narrows where it used to read; `mypy --strict` makes that mechanical rather
than discretionary, but it is four sites today and every future site as well. `core/types.py`
grows a private base and a public model for a case that will, if §9 works, never recur — the
cost of representing history honestly is carrying the representation forever. A reader of
`EgressBinding` now has to look at a base class to see three of its four members, which is
the price of declaring them once. And the two parked rows on the owner's hub stay
unanswerable: this ADR makes them **legible**, not resumable, and nothing here reclaims a
park whose origin was never recorded.

**What would trigger revisiting this.** A second epoch — a further required member on a
stored model — fires §9's deferred payload-version question and may replace this ADR's shape
wholesale for future epochs while leaving this one's representation standing. An ADR that
establishes standing authorisation for egress recipients (ADR-0181 §12's second bullet) must
read §7's floor before it relaxes anything. And a route by which an unresumable park may be
explicitly retired — the open question `pending_confirmation`'s docstring calls "the same
open question a permanently unanswerable park already poses" — would give these rows a
disposition this ADR deliberately does not.

## Alternatives considered

**A three-valued origin on the binding** — `planned_with_external_content` becoming
`bool | Literal["unrecorded"]`, or an enum with three members. Rejected, and not narrowly.
It changes the type of a live field, so every ADR-0181 §10 test asserting a `bool` moves and
every consumer gains a third branch; `ConfirmationEgress` inherits the third value and the
wire type widens, moving `PROTOCOL_VERSION` for a history problem. The decisive objection is
upstream of all of that: a third value is expressible on a **newly constructed** binding, so
every live builder acquires a way to not answer — which is exactly what ADR-0181 §3's
"required with no default" exists to deny ("Requiring the field forces every builder to
answer"). A representation for old rows must not be a defaulting hatch for new ones.

**A second field on `PermissionDecision`** — the binding stays `EgressBinding | None` and a
marker beside it says the origin was never recorded. Rejected. The binding cannot be
constructed at all without the required member, so the marker does not actually let the row
decode unless the binding slot goes `None` — which ADR-0150 §1's second clause forbids. And
a decision carrying two fields that must agree is the join ADR-0150 §1 refused in terms:
"no lane spreads the binding's facts across several fields of either model".

**A read-side projection type returned by the readers** — `get` and friends returning
`PermissionDecision | LegacyRecord`. Rejected. It changes four `AuditTrail` signatures, which
is a Protocol change with every consumer forced to narrow at the call rather than at the one
field that is actually uncertain; `recent` and `export` would return heterogeneous lists; and
a `LegacyRecord` either duplicates every member of `PermissionDecision` or throws them away.
Putting the union at the field that varies is strictly less surface for strictly more
precision.

**Leave it as it is, and let the four readers raise.** Rejected, and this was the standing
answer until #1465. It is defensible for `get` and `resolution_of`, which name one row. It is
not defensible for `recent` and `export`, which are all-or-nothing: two rows deny the user
every other row and defeat the portability obligation ADR-0021 §4 says `export` discharges.
"The record is unreadable" is a true statement about two rows and a false one about the
trail.

**A migration that rewrites, versions or annotates the rows.** Rejected on the two grounds
§4 states, either of which is sufficient: it would supply a value ADR-0181 §3 and §4 forbid
supplying, and it would rewrite an appended record in a store that has no `update` by
design. #1451 reached the same place from the fabrication side alone; the append-only ground
is the second lock.

**Retire the rows — `clear`, or a targeted delete.** Rejected as this ADR's answer, and
partly available as the user's. Wholesale erasure is the user's right (ADR-0021 §4) and
nothing here removes it. A *targeted* delete is refused outright: "selective erasure of an
audit trail is indistinguishable from tampering with it", and a system that deletes the
records it finds inconvenient to represent has answered the wrong question.
