# 23. Naive datetimes are rejected, not normalised

- Status: Accepted, §2 amended by ADR-0030
- Date: 2026-07-20
- Amended: 2026-07-21 by ADR-0030 — §2's conversion is completed by a
  canonicalisation: the stored value is a plain datetime rebuilt from a
  conversion result that is exactly a datetime with tzinfo is UTC and a zero
  offset, so an aware value whose astimezone preserves a subclass is refused
  rather than stored. §3 is unchanged and is the ground for it: pairing digits
  and an offset read separately from one value would be core attributing an
  offset those digits never carried. The naive-rejection rule, the awareness
  spelling, the conversion-overflow edge and §§4-6 stand as ratified.
- Complements: ADR-0005, ADR-0008, ADR-0009, ADR-0014, ADR-0021 §4 — each types
  a `datetime` field "tz-aware"; only ADR-0009 also fixes UTC storage, which this
  ADR settles uniformly. Per ADR-0019 the reference runs one way; their statuses
  are unchanged. See §5.
- Defers to ADR-0026: the injected-clock seam (a *producer* of instants, not a
  stored field) and any resulting ADR-0008 amendment. See §6.

## Context

`core/types.py` holds thirteen datetime fields. Ten run through a field
validator that does two things at once: it attributes UTC to a *naive* value,
and (usually) converts an *aware* value to UTC — eight validators, whose
attributing lines are 127, 303, 348, 550, 598, 819, 882, 999.

**Three have no validator at all.** `Provenance.last_updated`,
`EpisodicMemory.occurred_at` and `SemanticMemory.valid_until` accept a naive or
non-UTC value and store it untouched; `last_updated` is even documented
"(tz-aware)", a promise nothing enforces. So the status quo is not one
convention but three: coerce-and-convert, coerce-only, and no rule.

ADR-0021 §4 departs from it. `PermissionDecision.decided_at` is **rejected** at
construction when naive, justified as being done "like every other instant in
`core`". **That clause is false** — it is the only place in `core` that rejects.
The error is in the comparison only; the argument §4 gives after it stands on its
own, and is why this ADR exists rather than a correction patch:

> the trail is durable and ordered, so a naive value is reinterpreted against
> whatever the host's local zone happens to be at read time, and it sorts
> incoherently against the aware values beside it.

Two further facts came out of examining the sites, neither previously recorded.

**Even among the ten, the convention is not uniform on its second axis.** Six
validators call `value.astimezone(UTC)` on an aware value; two —
`MemoryBase.expires_at` and `CurrentContext.now` — store an aware non-UTC value
unchanged. "Normalised to UTC" is already two behaviours wearing one name.

**The validator is not the only way a timestamp is written.**
`model_copy(update=...)` does not re-run validators, and the codebase
half-knows it: `orchestration/loop.py:407` normalises its injected clock before
installing `expires_at` this way, while `memory/ingest.py:143` runs the *same*
write with no such guard. So naive values circulate not from callers passing
them to constructors — ruff's `DTZ` rules make that hard (`CONTRIBUTING.md` →
Typing & code style) — but from injected clocks through paths that bypass a
`core` validator, some guarded and some not.

PR #119 implements ADR-0021 as ratified and is blocked on this. It also added
two behaviours ADR-0021 does not specify: UTC **conversion** of aware
`decided_at` values (in scope here) and a hex constraint on `parameters_digest`
(not).

## Decision

### 1. Separate conversion from attribution

The single word "normalise" hides two operations with opposite risk profiles.

- **Conversion** — `value.astimezone(UTC)` on an aware value. Information
  *preserving*: it changes the representation, not the instant.
- **Attribution** — `value.replace(tzinfo=UTC)` on a naive value. Information
  *inventing*: it asserts an offset the caller never supplied.

Every argument for the current convention is an argument for conversion. Every
argument against it is an argument against attribution. They are ratified
separately below.

### 2. Conversion is mandatory and uniform

**Every instant a validator sees is stored as UTC** — an aware value converted
with `astimezone(UTC)`, no field opting out. The qualifier is deliberate:
`model_copy(update=...)` skips validators (a pydantic property no type can
close), so the invariant holds *at the validation boundary*, and a write that
reaches past it must re-validate. That mechanism already exists —
`planning/execution.py:72` re-validates after `model_copy` for exactly this
reason — and extending it to timestamp writes is the migration's job. The
enforceable invariant is "validated construction is UTC", not "every object is
UTC", which the language will not guarantee against a caller reaching past the
validator.

This is not merely tidiness. Python compares two aware datetimes sharing a
`tzinfo` by their naive wall-clock values, ignoring `fold`, so during a DST
repeated hour `01:15 fold=1` (the later instant) compares as *earlier* than
`01:45 fold=0`; converting to UTC makes same-`tzinfo` comparison identical to
instant comparison. PR #119 found this on `decided_at`; this clause ratifies the
fix and extends it to `MemoryBase.expires_at` and `CurrentContext.now`. For
those two the gap is latent — both are compared against a UTC clock, and Python
compares *differing* tzinfos by instant correctly, so it needs such values
ordered among themselves: a seam, not an outage. One edge: a value near
`datetime.min`/`max` at a non-UTC offset passes §3's awareness test yet overflows
`astimezone(UTC)` — rejected with the same field-naming error, not leaked as
`OverflowError`, since "convertible to UTC" is part of what the validator checks.

**This rule lives in one shared type, not a per-field validator.** The three
unvalidated fields exist because a per-field validator is opt-in: nothing catches
the field that omits it. So §2 and §3 are carried by a single `Annotated`
instant type — the pattern `Identifier` and `VisibleIdentifier` already use in
`core/types.py` — that every datetime field is typed with. Using the type is the
enforcement, and a bare `datetime` on a `core` field is forbidden — **a required
gate check** (triad-style: it discovers every datetime field in `core` and fails
on a bare annotation or an unvalidated default) makes the omission fail the gate,
not merely a reviewable smell. Its two paths — bare annotation, and each default
policy including `default_factory` — need *independent* negative fixtures, since
either check can regress while the other stays green and a combined fixture masks
which failed.
The type is scoped to **instants** — absolute points in time, which all thirteen
fields are.
A *civil* time (a recurring "09:00 `Europe/Berlin`", whose meaning is the wall
clock, not an instant) must not be UTC-converted — that shifts its hour across
DST — so it would be a distinct type with its own decision, which this rule
neither covers nor pre-empts. One caveat the type must close: pydantic skips
validating a field *default*, so an instant field with a `default_factory`
clock needs `validate_default` (or a ban on datetime defaults), else a naive
default slips the type. Defining the instant type with these edges is the
migration's (#130); mandating that the rule not rest on opt-in validators is
this ADR's.

### 3. `core` never attributes an offset

**A naive datetime is rejected** with a `ValueError` naming the field. No type
in `core/types.py` attributes an offset to a value that arrived without one.

The reason is not that attribution is always wrong. It is that
**`core/types.py` is the one layer that cannot know whether it is right.** A
shared type validates values arriving from everywhere: a UTC timestamp we wrote
and read back through a format that drops offsets, and a datetime a user typed
meaning their own wall clock. For the first `replace(tzinfo=UTC)` *restores* a
fact; for the second it *fabricates* one; the two are indistinguishable at the
validator, and coercing there resolves the ambiguity in the fabricating
direction, silently, every time.

Attribution is legitimate exactly where provenance is known — in the adapter
that decoded the value, which knows it wrote UTC and may therefore say so. This
decision does not delete attribution; it moves it to the layer entitled to
perform it.

**This bounds a legacy-data migration, but does not design it.** Once `core`
rejects naive values, a persisted row with a naive timestamp stops decoding
(`SqliteMemoryStore._decode`, `:250`). New writes are mechanical — the validator
covers construction, each `model_copy` write normalises or rejects (§2). Stored
rows are a real migration, and this ADR sets only its two contract-level bounds:
a live row may not be dropped or hidden (ADR-0004 §6's view/export/delete,
ADR-0007 §3's all-live guarantee for `export()`), and no offset may be attributed
to a stored value silently. Everything the migration must resolve *within* those
bounds is `memory/`'s (#130), and substantial enough to warrant its own record:
whether the numeric expiry index or the JSON string is authoritative for a legacy
`expires_at` (`sqlite_store.py:211` reads a naive value host-local, so they can
disagree by the host offset), how a converted database is fenced so a naive write
cannot slip in after it, and how the fact that an offset was assumed is carried —
`MemoryStore.export()` yields only `MemoryRecord`, so a per-row provenance flag
would be a `core` change, not a migration detail. Those are #130's to answer or
escalate; the ADR's job is to make the bounds non-negotiable, not to pick the
mechanism between them.

### 4. There is no category test, because there is no category

Rejection is right for a reason that has nothing to do with durability:
**`core/types.py` cannot know a value's provenance**, so it cannot know whether
attributing UTC restores a fact or fabricates one (§3), and that is true of an
advisory instant exactly as much as a durable one. The uniform rule follows from
where the type sits, not from what each field is later used for.

A tempting middle position argues otherwise — attribute hint-like instants,
reject durable ones — and it fails on application, the only test that matters for
a rule governing the next field. The categories will not divide the fields:
"durable" claims almost all of them (`expires_at`, `created_at`, `deadline`,
`occurred_at`, the execution timestamps), `CurrentContext.now` is a clear hint
("advisory ... never stored"), and others resist a clean call —
`FeedbackEvent.created_at` is discarded when its event yields no proposal
(ADR-0009 §4). A test that cannot classify its own existing inputs cannot govern
new ones: it would oblige every future author to guess a category, with nothing
checking the guess and a wrong timestamp — unfalsifiable afterwards — as the
failure. Uniform rejection removes the decision instead of adjudicating it.

### 5. Complementary to the field clauses; the clock seam is ADR-0026's

ADR-0005, ADR-0008, ADR-0009, ADR-0014 and ADR-0021 §4 each type a `datetime`
field and require only that it be "tz-aware", saying nothing about UTC versus any
other offset — the de-facto UTC convention lives in the validators, not in those
decisions. **The one field-level precedent is ADR-0009**, whose
`FeedbackEvent.created_at` is already "tz-aware (normalised to UTC)"; UTC storage
is preserved and generalised, not invented. For every *field*, then, settling the
storage zone uniformly is **complementary**: no prior field requirement changes,
awareness and naive-handling stand verbatim.

ADR-0019 decides what that means for statuses: its "Relationship to ADR-0003"
holds that the grounds for touching an accepted ADR are amendment or
supersession, and that for a complementary decision "the reference runs one
way" — the older ADR is not edited to point back. So the field relationships edit no status — including
ADR-0021's; an earlier draft called this an *extension* and edited it, the error
ADR-0019 names, since nothing in §4 is withdrawn. Correcting §4's false "like
every other instant" rationale is forward commentary, not a decision change, so
it too needs no status edit.

**ADR-0008's `CurrentContext.now` field is complemented like the rest** — its
storage zone was never decided, so it too gets no status edit. But ADR-0008 also
owns the injected *clock* that produces `now`, and reconciling a naive-rejecting
`core` with that seam's availability guarantee is a genuine change with its own
contract questions. This ADR does not make it; §6 defers it to ADR-0026. So no
status here is edited, ADR-0008's included.

**"Aware" means what Python means**: `utcoffset()` returns a value. A `tzinfo`
that is set but indeterminate — `utcoffset()` returning `None`, issue #36 — is
therefore not aware, and §3 **rejects it**. This ADR decides that rule;
`tzinfo is not None` was always the wrong spelling, and PR #119 already spells it
correctly for `decided_at`. #36 stays open as the work of correcting the
remaining sites, not an open question about what should happen.

### 6. The injected-clock seam is deferred to ADR-0026

This ADR governs the **instant-valued `core` fields** — the thirteen values
`core` validates, durable or advisory alike (`CurrentContext.now` is advisory,
§4) — via the shared `UtcInstant` type. A **clock** is different: not a stored
field but a *producer* of instants, injected as `now: Callable[[], datetime]` in
`context` (ADR-0008 §5), `planning` (ADR-0014), `memory`, and `orchestration`.
Making those producers guarantee an aware reading — the narrowing to an
aware-by-construction return, its runtime enforcement, the localization-overflow
range a valid instant must still satisfy, the `ContextError` failure semantics,
and the resulting amendment to ADR-0008 §§4–5 — is a distinct contract with its
own reconciliation, which review showed keeps generating questions of its own.
It is **deferred to ADR-0026** and not decided here.

The two migrations are **dependent, and the producer's leads.** For a field a
clock feeds, today's naive reading is coerced by *the `core` validator*
(`ExecutionState.updated_at` via `_revalidated_state`, say), not by the clock —
so adopting the rejecting `UtcInstant` there before that producer is guaranteed
aware would break a naive test or config clock. So #130 does not migrate a
clock-fed field to `UtcInstant` until ADR-0026 has made its producer aware (or
retains the existing normalisation at that boundary as a shim until it does);
recorded fields no clock feeds migrate independently. ADR-0026 lands its
producers first, then #130 tightens the fields they feed.

## Consequences

- **PR #119 changes nothing.** Its `decided_at` behaviour — reject naive,
  reject an indeterminate offset, convert aware to UTC — is exactly what §§2–3
  ratify. The unspecified conversion it added is now specified. The
  `parameters_digest` hex constraint is untouched by this ADR, neither blessed
  nor forbidden.
- **All thirteen fields change**: the eight validators (covering ten fields)
  flip to rejecting, and the three unvalidated fields gain a validator they
  never had. That is a breaking change to `core`, and it is **not** simply
  deletion.
- **Injected clocks feed `core` and are ADR-0026's, not this ADR's.** They come
  in two shapes: some *attribute* UTC to a naive reading (`loop.py:407`,
  `memory/store.py:67`, `sqlite_store.py:_now_epoch`, `testing/memory.py:54`,
  `context/sources.py:107`), which is §3's fabrication relocated to a subsystem;
  others are *unguarded bypasses* that pass a naive value straight through
  (`memory/ingest.py:143`). Making every clock produce an aware reading — so none
  feeds a naive value to a stricter `core` — is the producer-side contract §6
  defers to ADR-0026; until it lands they keep normalising, so nothing breaks.
- **Legacy naive rows need a real migration, bounded but not designed here**
  (§3): they may not be dropped (data rights) and may not be silently
  attributed, but the retention-authority, fencing, and provenance questions
  between those bounds are #130's — substantial enough to warrant their own
  record. This is where the migration meets existing data, not merely a tighter
  validator.
- `core/types.py` is the repo's highest-collision surface, so the migration is
  sequenced by owning subsystem in #130, not ridden along with this ADR (golden
  rule 5).
- **A caller that today passes a naive datetime gets a `ValidationError`**
  where it used to get a working object. Pre-1.0 this is allowed to happen; it
  is still the sharpest edge here, and the case against it is below.
- Tests carrying `# noqa: DTZ001` to exercise the coercion invert to asserting
  rejection; `FakeContextProvider`'s local indeterminate-`tzinfo` guard becomes
  redundant once the aware-means-`utcoffset()` rule lands everywhere (#36).

### The strongest case against this decision

Normalising is a *forgiving* boundary, and the fact it invents is **stable**: a
naive value coerced to UTC behaves identically on every host, whereas one left
uncoerced drifts with the reader's zone. So ADR-0021 §4's travelling-laptop
failure is one the coercion largely *prevents* — the argument this ADR builds on
is weaker than it reads. And `DTZ` stops naive datetimes at lint time, so
rejection buys little inside the repo while turning a formerly-working call into
a runtime failure deep in a pipeline.

The answer, not a total one: stable-and-wrong is the worse failure, because it is
unfalsifiable — a record reading 14:00 UTC when the human acted at 14:00 in
Berlin is forever indistinguishable from a correct one, whereas a
`ValidationError` names its cause at entry. And `DTZ`'s reach is the complement
of where the risk lives — it governs first-party construction, while naive values
arrive from deserialisation, storage, user input and injected clocks, which no
linter sees. What it does establish is that this is a **correctness and
auditability** decision, not a bug fix — which is why §4 refuses the category
test rather than denying the categories differ.
