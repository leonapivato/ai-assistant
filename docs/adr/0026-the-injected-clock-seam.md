# 26. The injected clock seam: a clock produces an aware instant

- Status: Accepted, §2 amended by ADR-0030
- Date: 2026-07-21
- Amended: 2026-07-21 by ADR-0030 — §2 step 4 converts and then
  canonicalises through core's single shared canonicaliser, applying §3's range
  check to the canonical value; a reading whose conversion is not exactly a
  datetime carrying tzinfo is UTC is rejected with the owner-labelled ValueError.
  Step 1's "not a datetime at all" check is unchanged and is deliberately not
  tightened to an exact type. Everything else in §2 stands: wrapped at storage,
  checked per reading, converting rather than rejecting, the total failure path,
  and the reading/invocation boundary. §§1, 3-7 are unaffected, and §6's
  amendment to ADR-0008 is untouched.
- Decides: what ADR-0023 §6 defers — the *producer* side of the instant
  convention. ADR-0023 is **Accepted** (merged in #129), so its §6 ordering
  constraint is ratified, not provisional. What is *not* yet in the code is its
  **migration**: `UtcInstant` does not exist in `src/` and no field validator has
  flipped to rejecting. This ADR is written against the ratified §6 and does not
  restate or reopen ADR-0023's field-side decision.
- Amends on ratification: ADR-0008 §§4–5. The edit is **not** made by this
  change — see §6 for its exact form and why it waits.

## Context

The pipeline injects a clock. Ten constructors across five subsystems take
`now: Callable[[], datetime]`, each defaulting to a module-local
`_utcnow() -> datetime` returning `datetime.now(UTC)`:

| seam | file |
| --- | --- |
| `ClockContextSource` | `context/sources.py:69` |
| `PlanExecution` | `planning/execution.py:108` |
| `InMemoryPlanStore` | `planning/store.py:44` |
| `InMemoryMemoryStore` | `memory/store.py:54` |
| `SqliteMemoryStore` | `memory/sqlite_store.py:57` |
| `MemoryIngestor` | `memory/ingest.py:69` |
| `LearningLoop` | `orchestration/loop.py:179` |
| `FakeMemoryStore` | `testing/memory.py:41` |
| `FakePlanner` | `testing/planning.py:80` |
| `FakePlanStore` | `testing/planning.py:120` |

Two ADRs name this seam and neither constrains what it may return. ADR-0008 §5
gives `ClockContextSource` "an injectable `now: Callable[[], datetime]`
(defaulting to UTC wall-clock), matching the memory subsystem, so context is
deterministically testable". ADR-0014 says `PlanExecution` "takes an injectable
`now: Callable[[], datetime]`, matching `memory` and `context`, so timestamps
are deterministic in tests". Both describe the code accurately; both stop at
*injectable*. `InMemoryPlanStore`'s clock is in neither — ADR-0014 §5 decides
`PlanStore` without mentioning that it reads a clock for `PlanExport`.
`permissions` has no clock seam at all, by ADR-0021's own design: `decided_at`
is "supplied by the caller that records", not read from a clock.

**The difficulty is that awareness is not in the type.** `datetime` is one type
for aware and naive values, so no annotation states the obligation and no `mypy`
run can check it. The obligation therefore got solved once per site, five ways
and one omission:

- Five sites **attribute** UTC to a naive reading — `context/sources.py:107`,
  `memory/store.py:67`, `testing/memory.py:54`, `orchestration/loop.py:408`,
  `memory/sqlite_store.py:243`. That is ADR-0023 §3's fabrication, relocated to
  a subsystem: `replace(tzinfo=UTC)` on a value whose provenance the seam does
  not know.
- One site **bypasses** the question — `memory/ingest.py:143` writes
  `self._now() + ttl` into `expires_at` through `model_copy(update=...)`, which
  skips validators. `orchestration/loop.py` guards the *identical* write and
  says why in a comment; `ingest.py` does not.
- The rest rely on a downstream `core` field validator, which is precisely what
  ADR-0023 removes: `planning/execution.py` reaches `ExecutionState.updated_at`
  through `_revalidated_state`, whose docstring already says it "also normalises
  `updated_at`: an injected clock returning a naive datetime would otherwise be
  written straight through".

So today's naive-clock safety net is a mixture of local attribution and `core`
coercion. ADR-0023 removes the coercion half and, in §6, defers the producer
half here — together with the ordering constraint that makes the two safe to
land separately.

## Decision

### 1. A clock is a named contract in `core`, not a callable shape

`core` gains **`Clock`**: a zero-argument callable returning an instant that is
aware, convertible to UTC, and localizable to any zone (§3). Every seam in the
table declares `now: Clock` in place of `now: Callable[[], datetime]`.

The alias does not enforce anything — §2 does. What it does is give the
obligation one place to be written, and make every consumer's constructor
signature change, so the requirement arrives at each site rather than being
rediscovered there. Nothing states it today, which is why five sites answered it
independently and one did not answer it.

**`Clock`'s return element is `UtcInstant` once ADR-0023's type exists, and
`datetime` until then**, with no behavioural difference: Python never checks a
callable's return annotation at runtime, and §2 is what decides. This is
deliberate — it is what lets this ADR's producers land without waiting on
ADR-0023's migration, which is the order §5 requires.

**Placement is decided, not left open: `core/clock.py`, and specifically not
`core/types.py`.** ADR-0014 §4, as restated by ADR-0016 §2, is that
"`core/types.py` holds no **subsystem logic**. It may hold semantics
**intrinsic** to a type it defines" — intrinsic meaning computable from the
type's own declaration, independent of policy, configuration, context or a
clock, and the same answer for every consumer. A guard that calls an injected
callable is not a semantic of a type at all, so it does not belong in
`types.py`.

**It does belong in `core`, because that rule is about `core/types.py`, not
about `core`.** No ratified decision makes `core` behaviour-free, and the code
says otherwise: `core/logging.py` holds `redact_sensitive`, `_redact_mapping`
and `install_redaction` — executable cross-cutting enforcement every subsystem's
logging runs through — and `core/config.py` holds `load_settings()` and
`Settings`' validators, which read configuration. `CLAUDE.md`'s own map lists
`core` as "contracts (Protocols), shared types, config, errors". `checked_clock`
is that same category: shared machinery with exactly one definition, which is
the point — §2's whole argument is that five subsystems already answered this
question five ways and one omitted it. Pushing it into an owning subsystem
recreates that; putting it in a shared non-`core` layer would mean a layer
*below* `core` that `core` may not depend on, inverting golden rule 2 for one
function. It keeps golden rule 2 as written: nothing but the standard library.

Two things the guard deliberately does **not** carry, so it stays shared rather
than becoming one subsystem's rule housed in `core`:

- **No configured zone.** §3's range is a flat margin off `datetime.min`/`max`,
  chosen precisely so the check never reads `Settings.timezone` — it asks
  "representable under *any* localization", which is a fact about `datetime`
  arithmetic, computable from the type's own bounds and identical for every
  consumer. Had it depended on the configured zone it would be `context`'s rule
  wearing `core`'s coat, and it would belong in `context`.
- **No failure policy.** `core` raises `ValueError` and nothing else; which
  `AssistantError` a violation becomes is each subsystem's, at its own boundary
  (§4). The `owner` label is a string the caller supplies for the message, not a
  policy `core` selects.

### 2. Enforcement wraps the clock once, where the clock is stored

`core` gains **`checked_clock(now: Callable[[], datetime], *, owner: str)
-> Clock`**. Every constructor in the table stores
`self._now = checked_clock(now, owner=...)` rather than the raw callable. The
`owner` label is supplied by the caller and not inferable: the same fixture
callable can be injected into `ClockContextSource` and `PlanExecution` at once,
so `core` has nothing to distinguish them by, and a diagnostic that cannot name
which seam received the bad reading is the one thing this guard exists to
provide. On each reading the wrapper:

1. **rejects** a reading that is not a `datetime` at all;
2. **rejects** a reading whose `utcoffset()` returns `None` — naive, or a
   `tzinfo` that is set but indeterminate. That is ADR-0023 §5's spelling of
   "aware", and issue #36's rule, applied at the producer;
3. **rejects** a reading outside §3's range;
4. converts with `value.astimezone(UTC)` and **re-checks the converted value**
   before returning it — a `datetime` whose `utcoffset()` is exactly zero and
   which is still in range.

Step 4 checks its own output, which is the only step that can. `astimezone` is
overridable: a `datetime` subclass can satisfy steps 1–3 and still return a
naive or non-UTC value from it, and the wrapper would then certify precisely the
value this ADR exists to stop, on the `model_copy` paths that have no validator
behind them. Validating the result rather than trusting the conversion costs one
more comparison and removes the assumption.

**The guard is total over the reading, because the annotation is not.** §1 is
explicit that `Clock` enforces nothing at runtime, so `now=lambda: None` is a
reachable wiring bug; unguarded it surfaces as a raw `AttributeError` from
`None.utcoffset()`, and a custom `tzinfo` whose `utcoffset()` raises escapes as
whatever it raised. Every step above — the type check, `utcoffset()`, the range
comparison, `astimezone(UTC)` — therefore runs inside the guard, and any
`Exception` from any of them becomes the owner-labelled `ValueError` with the
original attached as its cause. A guard whose own failure modes bypass the
failure path it specifies would be enforcing nothing at exactly the inputs it
exists for.

**The guard covers the reading, not the invocation.** An exception raised by the
clock callable *itself* propagates unwrapped. That is the clock's own failure,
already carrying its own type and cause, and relabelling it `ValueError` would
destroy both; `BaseException` (a cancellation, a `KeyboardInterrupt`) must pass
through for the same reason. The boundary is stated here rather than left to the
implementation because "which exceptions become the owner-labelled `ValueError`"
is precisely what §4's failure semantics rest on.

Three properties of that placement are the decision, not incidental.

**Wrapped at storage, not at each read.** One site per constructor, which a call
site cannot forget. Per-call guarding is what produced the current state:
`orchestration/loop.py` remembered and `memory/ingest.py:143` did not, on the
same write into the same field.

**Checked per reading, not once at construction.** A clock is a callable whose
readings change. A fixture that is aware on its first reading and naive on its
third is an ordinary test double, so validating the clock once at startup would
certify a property it does not have.

**Converting, not merely rejecting.** ADR-0023 §2 makes UTC storage mandatory
and uniform because Python compares two aware datetimes sharing a `tzinfo` by
wall clock, ignoring `fold`. Converting at the producer means every downstream
comparison — including the ones that never reach a `core` validator, like
`SqliteMemoryStore._now_epoch`'s `timestamp()` and `InMemoryMemoryStore`'s
expiry check — sees UTC. Conversion is information-preserving (ADR-0023 §1), so
this adds no fabrication anywhere.

The five attributing sites listed in the Context are **deleted** by the
implementing change, not left in place. Each is a fabrication `core` is about to
stop performing; leaving any one of them would leave a path on which a naive
reading still silently becomes UTC, which is the outcome ADR-0023 §3 exists to
prevent. `core/types.py:303`'s `CurrentContext.now` validator is a *field*
validator and stays #130's to remove.

The default `_utcnow` at all ten sites already conforms, so the wrapper costs one
branch and one `astimezone` per reading and changes no default behaviour.

### 3. The valid range is "localizable", not merely "convertible to UTC"

ADR-0023 §2 bounds a *field*'s instant by `astimezone(UTC)` overflow. A clock
reading must clear a stricter bar, because `context` does not only convert it:
`ClockContextSource` localizes it to the configured zone
(`sources.py:108`) to derive `time_of_day`, `is_weekend` and
`within_working_hours`. A value that converts to UTC without overflowing can
still overflow that second `astimezone`.

**A valid reading, expressed in UTC, lies within
`[datetime.min + 1 day, datetime.max - 1 day]`.** The margin is a flat day
rather than the configured zone's actual offset, deliberately: computing that
offset at the boundary requires the localization being guarded. One day covers
every offset the tz database carries, historical LMT ones included — its widest
are `Asia/Manila`'s −15:56:08 and `America/Metlakatla`'s +15:13:42, both well
inside a day, and the widest modern offset is `Pacific/Kiritimati`'s +14:00. The
bound is therefore coarse by about eight hours at the extremes of a range no
clock will read, and buying exactness there would cost the very computation it
protects.

A reading outside the range is rejected by §2 with the same error as a naive one
— not left to surface as an `OverflowError` from whichever `astimezone` reaches
it first. "Representable where it is used" is part of what the guard checks, the
same reasoning ADR-0023 §2 applies to its own UTC-conversion edge.

### 4. A non-conforming reading is a wiring bug, raised as the subsystem's error

`checked_clock` raises `ValueError` naming its `owner` label and what the
reading was — ADR-0023 §3's shape (which names the offending field), and the
only option open to `core`, which cannot know what its caller will do with the
failure. **Each
subsystem translates at its own boundary** into the `AssistantError` subclass it
already owns in `core/errors.py`. That is the pattern already in the code:
`memory/ingest.py:147` and `orchestration/loop.py` both turn `_expiry`'s
`OverflowError` into `MemoryStoreError`.

- `context` → `ContextError`
- `memory` → `MemoryStoreError`
- `planning` → `PlanningError`
- `testing` → **the error of the implementation each fake doubles**, not
  `ValueError`: `FakeMemoryStore` raises `MemoryStoreError`, `FakePlanner` and
  `FakePlanStore` raise `PlanningError`. A fake exists to certify a consumer
  against its contract (§7), so a fake that leaked the raw `ValueError` where
  the real store raises `MemoryStoreError` would certify a consumer's error
  handling against behaviour it will never meet in production — the one failure
  mode a canonical double must not have.
- `orchestration` → the error of the stage that read the clock, since
  `core/errors.py` defines none for `orchestration`: goal construction raises
  `PlanningError`, as `_turn_goal` already does for a blank utterance, and
  expiry raises `MemoryStoreError`, as `_expiry` already does.

For `context` this is the substantive clause. **It is not degradation.**
ADR-0008 §4 skips a failing *optional* source and leaves its facet `None`; the
temporal core is required and `now` has no `None` to fall back to, so a broken
clock cannot be skipped — `CurrentContext` could not be constructed without it.
It is also a wiring bug in exactly §4's sense: an injected dependency violating
its declared contract, which is the class §4 reserves `ContextError` for. So
`ClockContextSource.contribute()` raises `ContextError`.

**Propagating it takes a mechanism, and the mechanism is a required-source
marker on the source, not on the error type.** Today
`AssemblingContextProvider._safe_contribute` catches `Exception` and degrades
every source alike, so without a change the clock's `ContextError` is swallowed
and the caller sees only a later "could not assemble a valid context" from the
missing fields — the owner label and the cause both lost. Re-raising on the
error *type* instead is the wrong fix: a future optional source is entitled to
raise `ContextError`, and typing the decision would make it abort the request,
which is the degradation rule §4 keeps. So the marker is **`required`**, a
property a source may carry, read by the assembler as
`getattr(source, "required", False)`; `ClockContextSource` is the one source
that sets it `True`.

It is **not** added to the `ContextSource` Protocol, deliberately. A `Protocol`
member is mandatory for structural conformance and supplies no default to
classes that do not inherit it, so declaring it there would make every existing
source non-conforming — `tests/context/test_context_provider.py`'s
`_FailingSource` and `_LeakySource` implement `name` and `contribute` only, and
a bare `source.required` on them raises `AttributeError` inside the very
degradation path it was meant to select. Absent means optional, which is both
the safe default and the one that keeps ADR-0008 §2's seam additive. The
alternative — requiring every present and future source to declare `required` —
was rejected: it taxes every optional source to mark the one required one.

`_safe_contribute` then degrades an optional source exactly as today and does
not degrade a required one. Both paths are behaviour a test must pin: a
required source's failure reaching the caller with its cause intact, and an
optional source's failure — including one from a source with no `required`
attribute at all — still leaving its facet absent.

What does **not** change in §4: a conforming clock still performs no I/O and
still cannot fail per request, a malformed timezone is still a startup
`ConfigurationError`, and a failing optional source is still skipped.

Be plain about what this costs. Today a naive clock reading *does* yield a valid
`CurrentContext` — `core/types.py:303` attributes UTC to it. This ADR turns that
into a request-time `ContextError` **one change before** ADR-0023 would have
turned it into a `ValidationError`. It is a real behaviour change to a currently
working path, and it converts a silent fabrication into a loud failure, which is
ADR-0023 §3's trade taken at the producer.

### 5. Ordering: the producer leads, the field follows

Restating ADR-0023 §6's constraint, which this ADR is bound by. The two
migrations are **dependent, and the producer's leads.** For a field a clock
feeds, today's naive reading is coerced by the `core` validator, not by the
clock, so adopting the rejecting `UtcInstant` there before the producer is
guaranteed aware would break a naive test or config clock.

- **#130 does not migrate a clock-fed field to `UtcInstant`** until this ADR's
  guard is in place at that field's producer, or retains the existing
  normalisation at that boundary as a shim until it is. The clock-fed fields
  are `CurrentContext.now`, `MemoryBase.expires_at`, `Goal.created_at`,
  `Provenance.last_updated`, `ActionPlan.created_at`,
  `ExecutionState.updated_at`, `StepExecution.started_at`/`finished_at`, and
  `PlanExport.exported_at`. `ActionPlan.created_at`'s only producer today is
  `FakePlanner` (`testing/planning.py:108`), which is a clock seam like any
  other (§7) — a field whose sole producer is a fake is still clock-fed, and
  classifying it as independently recorded is exactly the mistake this ordering
  prevents. Recorded fields no clock feeds migrate independently.
- **This ADR does not wait for `UtcInstant`** (§1). Its guard is runtime and
  self-contained, so its producers land first; then #130 tightens the fields
  they feed.

### 6. What ratification does to ADR-0008

ADR-0017 §7 requires the operation performed on an amended ADR to be recorded
rather than inferred, and names the form's origin: "the precedent ADR-0018 set
for ADR-0016" — a qualified `Status` line plus a dated header note, with no
ratified text rewritten. ADR-0025's edit to ADR-0020 is the most recent instance
of that form, not its author; it decides nothing about amendment recording
generally. This ADR adopts the same form for the same reason ADR-0017 §7 gives:
"a second ADR inventing a second format is how a vocabulary stops being one."
ADR-0017 §7 wrote its
notes in accepted form *because it was ratified before merging*. This ADR merges
as `Proposed`, so **the edit is not made by this change** — writing "amended by
ADR-0026" onto ADR-0008 while ADR-0026 is only proposed is the state claim
ADR-0019 forbids. It is recorded here in the exact form to apply on ratification:

- ADR-0008's `Status` line becomes
  `- Status: Accepted, §§2, 4–5 amended by ADR-0026`.
- A dated note is appended to ADR-0008's header, after `Date`:
  `Amended: <ratification date> by ADR-0026 — §4's "a valid CurrentContext can
  always be built" now holds for a *conforming* clock: a reading that is naive,
  indeterminate, or outside the localizable range is a wiring bug and raises
  ContextError rather than being attributed UTC. §2's internal source seam gains
  an optional `required` marker — carried by a source, read by the assembler,
  absent meaning optional — so that failure is not degraded; optional sources
  degrade exactly as §4 says. §5's now: Callable[[], datetime]
  becomes the Clock contract of ADR-0026 §1. The startup-time treatment of a
  malformed timezone, the ContextSource/CurrentContext shapes, and everything
  else in §§2, 4–5 stand.`
- Nothing else in ADR-0008 is edited. Its §1, §3, §6 and Consequences stand as
  ratified.

ADR-0023 §6 anticipates an amendment to "§§4–5". §2 is added because §4's
propagation rule needs a marker on the source and §2 is where the internal
`ContextSource` seam is decided — a superset of what §6 anticipated, in the same
direction, not a departure from it. Nothing in §2's ratified text is withdrawn:
the seam stays internal to `context/`, and the only data crossing a subsystem
boundary is still `CurrentContext`.

### 7. Uniform across every seam; no advisory exemption

`SqliteMemoryStore._now_epoch` produces a float and never touches a `core`
field. `InMemoryPlanStore`'s clock only stamps an export. `CurrentContext.now`
is advisory and never stored (ADR-0023 §4). None of that earns an exemption, for
ADR-0023 §4's reason: the seam cannot know the provenance of the reading it was
handed, so it cannot know whether attributing UTC restores a fact or invents
one, and that is as true of an advisory instant as a durable one. A rule that
exempted "advisory" clocks would oblige every future author to classify their
clock, with nothing checking the guess and a wrong timestamp — unfalsifiable
afterwards — as the failure.

The `testing/` fakes are in scope for the same reason they exist: they are the
canonical doubles subsystems certify against (`CONTRIBUTING.md` → "Adding a
Protocol"). A fake looser than the contract certifies consumers that the real
implementation will reject.

## Consequences

- **Ten constructor signatures narrow** to `now: Clock`, and five attributing
  normalisers are deleted (`context/sources.py:107`, `memory/store.py:67`,
  `testing/memory.py:54`, `orchestration/loop.py:408`,
  `memory/sqlite_store.py:243`). `memory/ingest.py:143`'s unguarded write stops
  being unguarded without being touched, because its clock is now wrapped.
- **A naive test or config clock stops working** — it raises where it used to be
  silently attributed UTC. That is the point and it is the sharpest edge here.
  Tests injecting a naive clock (including any carrying `# noqa: DTZ001` to do
  so) invert to asserting rejection.
- **New `core` surface, consumed by five subsystems**: the `Clock` alias and
  `checked_clock`. It is *not* a `core/protocols.py` Protocol — a clock is a
  constructor parameter, not a Protocol member — so golden rule 5's "Protocol
  change" is not literally triggered. It is contract surface all the same, which
  is why it is an ADR and why it takes the architecture review.
- **#130 is unblocked for clock-fed fields** in the order §5 fixes, and issue
  #36 loses its clock-side sites: the guard is one place, spelled
  `utcoffset() is None`.
- **`ContextError` gains a request-time cause** it did not have. Callers that
  treated context assembly as infallible-by-construction (ADR-0008 §4) must
  handle it, though only a wiring bug can raise it. `context`'s internal source
  seam gains an optional `required` marker to carry that distinction (§4);
  absent means optional, so no existing source, fixture or `core` surface
  changes.
- **Revisit when** a *civil*-time source appears — a recurring "09:00
  Europe/Berlin", which ADR-0023 §2 reserves as a distinct type and which
  `Clock` deliberately does not cover — or when something needs a **monotonic**
  clock. `Clock` produces wall-clock instants; measuring an elapsed duration
  across a DST transition or an NTP step is a different contract this one does
  not provide and should not be stretched to.

### The strongest case against this decision

The guard runs on every clock reading in the hot path of every turn, to catch a
fault only first-party wiring can produce. `DTZ` already stops a bare
`datetime.now()` at lint time, and the default clock at all ten sites is
`datetime.now(UTC)`, which conforms. The realistic producer of a naive reading is
a test fixture — code the gate already runs, where a failure is cheap and local.
On that reading, §2 buys enforcement for a population of one and charges every
production reading for it, and a plain documented convention would do.

The answer, not a total one: the failure is not hypothetical here, it is present
in two forms simultaneously. `memory/ingest.py:143` writes a clock reading
straight into `expires_at` through a validator-skipping `model_copy` while
`orchestration/loop.py` guards the identical write and explains why — the
convention existed, was written down in a docstring, and was still missed one
file over. And the five sites that did remember solved it five separate times,
each free to drift. A convention that has already been forgotten once is
evidence about conventions, not about the odds of a naive clock. The price is a
branch and an `astimezone` per reading; the thing bought is that the answer
exists once.
