# 30. What counts as a `datetime` at a validating seam

- Status: Proposed
- Date: 2026-07-21
- Decides: issues #174 and #152 — the same question at two seams. #174 asks
  whether the exact-type restriction `UtcInstant` adopted inside an
  implementation PR (#164, `db0a93e`) is ratified or narrowed; #152 asks the
  same of ADR-0026 §2's `checked_clock`, which is ratified and not yet built.
  One answer binds both, because two guards that disagree about what a
  `datetime` is are two conventions.
- Amends on ratification: ADR-0023 §2 and ADR-0026 §2. Both are **Accepted**.
  Neither edit is made by this change — see §6 for its exact form and why it
  waits.

## Context

Implementing ADR-0023 (#130), review found a reproduced defect in `UtcInstant`.
A `datetime` **subclass** overriding `astimezone` could return a **naive** value
that was then stored inside a validated model, and a hostile `tzinfo` could
replace the field-naming `ValidationError` with an exception of its own. Because
`astimezone` preserves the subclass, any check-then-convert sequence leaves a
window in which an override runs between the two: verify the offset and it
flips while the digits are read; verify it again mid-read and it flips between
two of them.

The fix shipped in `db0a93e`. `_canonical_utc` now requires
`type(value) is datetime`, `tzinfo is UTC` and a zero offset, and rebuilds a
plain `datetime` from the components. It is pinned by
`tests/core/test_utc_instant.py` and documented at length in `core/types.py`.

**Two facts about the shipped code matter and are not in #174's summary.**

*The test is on the value the validator hands on, not the value it receives.*
`_canonical_utc` runs on the output of `value.astimezone(UTC)`. A subclass whose
`astimezone` returns a base `datetime` is therefore **accepted** — verified:

```text
class BaseOut(datetime):
    def astimezone(self, tz=None): return datetime(1970, 1, 1, tzinfo=UTC)

M(at=BaseOut(2026, 7, 21, 12, tzinfo=UTC)).at
# -> datetime.datetime(1970, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
```

"`UtcInstant` refuses every `datetime` subclass" is thus a *consequence* of
`astimezone` preserving the subclass, not the rule. The rule is narrower, and
stating it as the input-side test it is not would make ADR-0026's guard —
whose step 1 already tests the *reading* — diverge on transcription alone.

*The base implementation does not help, and not for the reason #152 gave.*
#152 offered `datetime.astimezone(value, UTC)` and it was rejected as not
closing the hole because `utcoffset()` is equally overridable. Measured, the C
implementation reads `tzinfo.utcoffset(self)` and ignores a Python-level
`utcoffset` override — so that half of the rebuttal is wrong. The direction
still fails, for a stronger reason: `datetime.astimezone(value, UTC)` returns
**the subclass**, so every read performed on its result is still interceptable.
The rebuttal's conclusion stands; its grounding is corrected here.

**Three structurally similar findings were ruled three ways on 2026-07-21**, and
#174 records the discomfort:

- **#119** — an overridable `model_dump()` on a `PermissionDecision` subclass.
  Waived; ADR-0021 §1 rules that a caller falsifying *its own* audit trail is
  unpreventable by any producer.
- **#152** — `checked_clock` converting through an overridable `astimezone`.
  Waived; the guard promises well-formedness of the reading, not correctness of
  the instant, and `now=lambda: datetime(1970, 1, 1, tzinfo=UTC)` defeats every
  conceivable guard without a subclass.
- **#174** — fixed, on the ground that the outcome is a *naive value surviving
  inside `core`*, the invariant `UtcInstant` exists to create.

Nothing breaks today. Pydantic parses every string input to a base `datetime`
(verified), and no `datetime` subclass is used anywhere in the project. The cost
is future and it is real.

## Decision

### 1. The rule is on the value handed on, not the value received

**A validating instant seam hands on a plain `datetime` rebuilt from a single
snapshot.** After conversion, and before anything is stored or returned, the
converted value must satisfy all of `type(v) is datetime`, `v.tzinfo is UTC`
and `v.utcoffset() == timedelta(0)`; the value that leaves the seam is a fresh
base `datetime` constructed from its components with `tzinfo=UTC`. Anything
else is refused with the seam's own field- or owner-naming `ValueError`.

This ratifies what `db0a93e` implements, stated as the output-side rule it is.
Two clauses of it are the decision and neither is decoration:

- **Exact type**, not `isinstance`. Only for an exact `datetime` are the
  components and the offset one immutable snapshot: they are C-level data, and
  every read of them is the C implementation, which cannot be intercepted. For
  an instance of a subclass each read is a method call the value gets to answer,
  so no ordering of checks wins.
- **Rebuilt**, not returned. `astimezone` is annotated to return a `datetime`
  and is not obliged to; pydantic does not re-validate what an `AfterValidator`
  returns. Rebuilding makes "stored as UTC" a property of the stored object
  rather than a claim the object makes about itself.

**A subclass on the way *in* is not forbidden by this rule.** It still has to
clear everything the seam already checks *before* converting — ADR-0023 §3's
awareness test at a field, ADR-0026 §2 steps 1–3 at a clock — so a subclass
whose `utcoffset()` returns `None` or raises is refused there, unchanged by this
ADR, however sound its conversion would have been. What §1 adds is the last
gate: having cleared those, a subclass is refused **iff** its conversion does
not yield an exact base `datetime` in UTC, which `astimezone` preserving the
subclass makes the overwhelmingly common case. Where a subclass does convert to
a base `datetime`, the seam reads every fact from that base value and accepts
it; the instant it yields is then the one the subclass itself stated, which is
§3's line.

### 2. No form keeps subclasses safely; each candidate ruled on

Three were considered. The first two fail outright.

**Re-validate after conversion, keeping the subclass.** This is the shape the
defect already defeats. A check made on a subclass is invalidated by the next
read, including the reads that copy the value out; `tests/core/test_utc_instant.py`
pins two working instances (`_ShiftySubclass`, `_FlipDuringComponentRead`). The
regress is not deep, it is unbounded.

**Route through the base implementation** — `datetime.astimezone(value, UTC)`.
Rejected, with the Context's corrected grounding: it returns the subclass, so it
moves the interceptable reads one step later rather than removing them.

**Accept a subclass and normalise to a base `datetime`** is the serious
candidate and it deserves a straight answer: *it does produce a well-formed
result*. Read the offset once, read the components once, compute
`datetime(components) - offset` with `tzinfo=UTC`, never call `astimezone` at
all. The output is always an exact, aware, UTC `datetime`. No naive value
survives. It closes #174's reproduced defect, it costs nothing at runtime, and
it would keep every third-party subclass working. **It is nevertheless
rejected**, for a reason that is not fastidiousness:

The offset and the components are two reads, and a subclass can change what it
reports between them. The pair the seam combines is then one the value never
simultaneously held, and the instant `core` writes down is one **no party ever
stated** — `core` supplying an offset for digits that never carried it. That is
ADR-0023 §3's fabrication exactly, performed by the layer §3 identifies as the
one that cannot know whether it is fabricating. `tests/core/test_utc_instant.py`
already pins the concrete instance (`_FlipOnConvert`): digits `09:00` and a
checked offset of zero, from a value that is on its own account `07:00Z`.

Only the exact type collapses the two reads into one. So: no form keeps
subclasses safely, and the blanket effect is accepted as the price of the
narrow rule, not mistaken for the rule.

### 3. What a guard is answerable for: pass on, do not compose

The contract, stated so the next seam does not re-derive it:

**A guard is answerable for the well-formedness of the value it hands on, and
for not composing a claim its source never made. It is not answerable for the
truth of a claim its source did make.**

The first clause is total and checkable. The last is not checkable at all, and a
guard that implied otherwise would be promising what nothing can deliver. The
middle clause — the composition clause — is the one that was implicit in all
three rulings and is ratified here.

This resolves the three rulings as one rule:

- **#119.** A `PermissionDecision` subclass with an overridable `model_dump()`
  states its own dict. The trail passes on the caller's own claim about the
  caller's own action. Nothing is composed. Waived correctly, and ADR-0021 §1
  independently rules the threat model out of scope.
- **#152 as raised.** A clock returning the wrong instant states that instant.
  The guard passes it on, whether it arrived from an overridden `astimezone` or
  from `lambda: datetime(1970, 1, 1, tzinfo=UTC)`. Nothing is composed. Waived
  correctly.
- **#174.** Copying digits out of a subclass and pairing them with a separately
  read offset composes an instant from parts. Fixed correctly.

**The stated ground for #174 was insufficient, and this ADR supplies the one
that holds.** "A naive value surviving inside `core`" justifies the
*canonicalisation* — rebuilding rather than trusting the conversion — but not
the *exact-type* restriction, because §2's third candidate also prevents a naive
value from surviving. Well-formedness alone therefore does not separate #174
from #152; the composition clause does. The three outcomes are consistent; one
of the three reasons was doing less work than it appeared to.

### 4. One canonicaliser, in one place, used by both seams

The anti-drift mechanism is not prose. `core/types.py`'s `_canonical_utc` is
**promoted to a named function of `core`** — one definition, imported by
`UtcInstant`'s validator and by ADR-0026 §2's `checked_clock`. A second
implementation of this test anywhere in `core` or a subsystem is forbidden.

**One such implementation exists today and is a bounded exception, not a
violation.** `memory/ingest.py:47` carries a second `_canonical_utc`: the
deliberate shim ADR-0023 §6 requires at a clock-fed field's producer until
ADR-0026's guard lands, tracked in #169 and documented as such in its own
docstring. The prohibition therefore **binds from the moment `checked_clock`
exists**, and #169's consolidation — deleting the shim and routing that write
through the shared function — is the act that discharges it. Ratifying this ADR
does not put the tree in violation of it; leaving the shim in place *after*
#169 would.

It stays in `core/types.py`, and that is consistent with ADR-0026 §1 rather
than a departure from it. §1 puts `checked_clock` in `core/clock.py` because a
guard that *calls an injected callable* is not a semantic of a type. The
canonicaliser calls nothing injected: it is a pure function of one value,
identical for every consumer, which is precisely ADR-0016 §2's "semantics
intrinsic to a type it defines". The import runs `core/clock.py` →
`core/types.py`, never the reverse.

**`checked_clock` is bound to it as follows**, amending ADR-0026 §2:

- Step 1's rejection of a reading "that is not a `datetime` at all" stays as
  written. It guards the reachable wiring bug `now=lambda: None` before
  `utcoffset()` is called on it, and it must not be tightened to an exact-type
  test: that would refuse a subclass whose conversion is sound, which §1 accepts.
- Step 4 becomes: convert, then **canonicalise**, then apply ADR-0026 §3's
  localizable-range check to the canonical value. A reading that does not
  canonicalise is rejected with the owner-labelled `ValueError`, inside the
  total failure path §2 already specifies.

Nothing else in ADR-0026 §2 moves: wrapped at storage rather than per read,
checked per reading rather than once, converting rather than merely rejecting,
and the guard covering the reading rather than the invocation all stand.

**The implementing change owes a shared adversarial table.** One list of hostile
values — subclass preserving its type, subclass converting to a base
`datetime`, conversion returning a naive value, returning `None`, returning a
non-`datetime`, flipping its offset during conversion, flipping during the
component read, a `tzinfo` whose `utcoffset()` raises — asserted against **both**
seams, so a change to one that the other does not follow fails the gate. A rule
in two places with two test suites is two rules waiting to diverge; that is the
condition #174 and #152 exist to prevent.

### 5. The cost, and why it is acceptable

Be exact: this refuses a class of values that are not hostile.

- **A third-party library returning a `datetime` subclass is refused.**
  `freezegun`'s `FakeDatetime` is the standard case: it is not a dependency
  today, and under this rule it could not be adopted for anything whose value
  reaches a `core` field or a clock seam.
- The workaround is one explicit call at the caller's own boundary, where
  provenance is known — the same layer ADR-0023 §3 assigns attribution to.

It is acceptable because **ADR-0026 already decided how this project fakes
time**: an injected `Clock`, at ten seams, uniform and with no advisory
exemption (ADR-0026 §7). Patching the global `datetime` module is the alternative that
design displaces, and a project that adopted both would have two mechanisms for
one job. The refusal makes that explicit at the boundary rather than leaving it
to be discovered when a faked timestamp is written to a durable record.

The residual cost is a library that returns a subclass for reasons unrelated to
faking time. That is a real future friction, it is priced, and it is the trigger
in the Consequences for revisiting.

### 6. What ratification does to ADR-0023 and ADR-0026

ADR-0017 §7 requires the operation performed on an amended ADR to be recorded
rather than inferred, and ADR-0026 §6 sets the form for an ADR that merges as
`Proposed`: the edit is **not** made by this change, because writing "amended by
ADR-0030" onto a ratified ADR while ADR-0030 is only proposed is the state claim
ADR-0019 forbids. Recorded here in the exact form to apply on ratification.

**Both earn a `Status` line change**, and the distinction ADR-0029 §9 draws is
what decides it. There, ADR-0016 §7's status was left alone because a later ADR
taking up an *explicit deferral* changes nothing in the earlier decision. Here
nothing was deferred: ADR-0023 §2 and ADR-0026 §2 each ratify a check, and this
ADR **narrows the set of values that check accepts**. ADR-0023 §2's "an aware
value converted with `astimezone(UTC)`, no field opting out" and ADR-0026 §2
step 4's "a `datetime` whose `utcoffset()` is exactly zero and which is still in
range" both read, as ratified, as sufficient conditions that are no longer
sufficient. That is a change to a past decision in ADR-0001's sense.

- **ADR-0023's `Status` line becomes**
  `- Status: Accepted, §2 amended by ADR-0030`.
- **A dated note is appended to ADR-0023's header, after `Date`:**

  `Amended: <ratification date> by ADR-0030 — §2's conversion is completed by a
  canonicalisation: the stored value is a plain datetime rebuilt from a
  conversion result that is exactly a datetime with tzinfo is UTC and a zero
  offset, so an aware value whose astimezone preserves a subclass is refused
  rather than stored. §3 is unchanged and is the ground for it: pairing digits
  and an offset read separately from one value would be core attributing an
  offset those digits never carried. The naive-rejection rule, the awareness
  spelling, the conversion-overflow edge and §§4-6 stand as ratified.`

- **ADR-0026's `Status` line becomes**
  `- Status: Accepted, §2 amended by ADR-0030`.
- **A dated note is appended to ADR-0026's header, after `Date`:**

  `Amended: <ratification date> by ADR-0030 — §2 step 4 converts and then
  canonicalises through core's single shared canonicaliser, applying §3's range
  check to the canonical value; a reading whose conversion is not exactly a
  datetime carrying tzinfo is UTC is rejected with the owner-labelled ValueError.
  Step 1's "not a datetime at all" check is unchanged and is deliberately not
  tightened to an exact type. Everything else in §2 stands: wrapped at storage,
  checked per reading, converting rather than rejecting, the total failure path,
  and the reading/invocation boundary. §§1, 3-7 are unaffected, and §6's
  amendment to ADR-0008 is untouched.`

- **Nothing else in either ADR is edited, and no other ADR is edited.**
  ADR-0021 §4's `decided_at` is a `UtcInstant` and inherits the rule without its
  text becoming false, so it gets no note — ADR-0029 §9's test, whether a
  sentence in the other ADR would now read as false, is not met there.

## Consequences

- **`db0a93e` stands.** `UtcInstant`'s behaviour is exactly what §1 ratifies and
  no `src/` change is required by the ratification itself. **One test is owed**:
  `tests/core/test_utc_instant.py` pins every *refusal* and pins that a plain
  input canonicalises, but nothing pins the path §1 makes normative — a subclass
  input whose conversion returns an exact base UTC `datetime` being **accepted**.
  Today that is emergent behaviour, so a later "refuse every subclass input"
  change would pass the suite while contradicting this decision. Filed as #183
  rather than absorbed here, since this change is docs-only.
- **The follow-on work is narrow and is not this change's**: promoting the
  canonicaliser to a named `core` function, binding `checked_clock` to it (§4),
  and building the shared adversarial table. It belongs to ADR-0026's
  implementation, which has not landed.
- **A caller passing an aware, in-range `datetime` subclass gets a
  `ValidationError` at a field and a `ValueError` at a clock seam**, where
  nothing in ADR-0023 or ADR-0026 as ratified says it would. Pre-1.0 this is
  allowed to happen; it is now stated rather than discovered.
- **`core`'s public surface grows by one function.** Small, and the point: the
  alternative is the same test written twice.
- **Issues #174 and #152 close on ratification**, #152 with its offered
  direction declined and its grounding corrected (Context).
- **Revisit when** a dependency the project actually wants returns a `datetime`
  subclass and the explicit conversion at its boundary proves impractical, or
  if CPython ever makes a base `datetime`'s components interceptable — the fact
  the whole rule rests on.

### The strongest case against this decision

The rule buys nothing against the threat it is aimed at. A caller who wants a
wrong timestamp in the database writes `datetime(1970, 1, 1, tzinfo=UTC)` and
every guard here waves it through — §3 says so in as many words. So the exact-type
test excludes a category of *implausible* attacks while charging a category of
*plausible* libraries, and §2's third candidate would have closed the reproduced
defect without charging anyone. Measured against outcomes rather than shapes,
this looks like a rule that prefers the elegance of an unbreakable invariant to
the cost it imposes.

The answer, not a total one: the difference between the two is what a wrong
timestamp *looks like afterwards*. A clock that returns 1970 is wrong in a way
the value records — the digits are the lie, and they can be read, compared and
disbelieved. An instant composed from a non-simultaneous read is wrong in a way
nothing records: every party stated something true, and the falsehood exists
only in `core`'s arithmetic. That is ADR-0023's own "stable-and-wrong is the
worse failure, because it is unfalsifiable", applied to the one case where the
falsehood would be `core`'s own. Refusing costs a `ValidationError` naming its
field at entry, which is the trade ADR-0023 §3 already took.
