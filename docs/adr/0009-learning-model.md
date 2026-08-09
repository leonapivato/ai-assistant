# 9. Learning: feedback capture that proposes memory updates

- Status: Accepted, §1 amended by ADR-0122
- Date: 2026-07-17
- Amended: 2026-08-09 by ADR-0122 — §1's `memory_kind` is no longer required of
  the caller: it becomes `MemoryKind | None`, and an absent value is resolved by
  `orchestration` before the processor is called — from the belief a *correction*
  touches, by one ranked read scoped to ADR-0122 §3's fixed resolution set, and
  from the intent alone for a stated *preference*, which establishes a
  `PreferenceMemory` and is resolved with no read at all. ADR-0122 §3 is the
  operative text; this note records the amendment and does not restate its terms.
  §1's reason is unchanged and is what the amendment implements — a
  correction's record type varies with what it corrects, so the layer that cannot
  see the target no longer supplies it. §§2–6 stand: §2's Protocol is untouched,
  §3's "`learning` never imports `memory`" is what places the resolution in the
  pipeline, §4's mapping runs on a resolved kind, §5's recorded interaction is
  unchanged, and §6's `PROCEDURAL`/`EPISODIC` deferral bounds what the resolution
  may select.

## Context

The request pipeline (`CLAUDE.md`) ends with `… → execute → learn/update
memory`. The `learning` subsystem owns that last step: per [VISION](../../VISION.md)
§"Feedback and Learning Loop", it converts corrections, edits, ignored
suggestions, repeated choices, and explicit ratings into *carefully scoped
improvements*. It is the piece that closes the roadmap's first vertical loop —
`conversation → retrieve context → respond → observe correction → propose a
preference update → reuse it next time` — by feeding the memory write-path we
already built.

Two forces shape the contract:

1. **The model proposes; a deterministic policy disposes** (VISION §7,
   [ADR-0005](0005-memory-model.md)). Learning must therefore emit
   `MemoryUpdateProposal`s, not write memory. The dispose half already exists:
   `MemoryPolicy` rules on a proposal and `MemoryIngestor` persists the outcome.
2. **`MemoryIngestor` is concrete in `memory/`, not a `core` contract.** So
   learning cannot depend on it without either bending golden rule 1 or promoting
   ingestion to a Protocol. We keep learning decoupled: it *produces* proposals,
   and the pipeline (`orchestration`, later) wires them to the ingestor.

This adds a new `core` type and Protocol, so it is ADR-worthy (golden rule 5).

## Decision

We will add a `FeedbackEvent` type and a `FeedbackProcessor` Protocol that turns
feedback into memory-update proposals, plus a first deterministic processor.

### 1. `FeedbackEvent` — structured, explicit, memory-affecting feedback

`core/types.py` gains:

```python
class FeedbackKind(StrEnum):
    CORRECTION   # the user corrected an existing belief
    PREFERENCE   # the user stated a preference

class FeedbackEvent(BaseModel):
    kind: FeedbackKind
    memory_kind: MemoryKind      # the typed memory this feedback establishes
    content: str                 # the canonical text, e.g. "office is in Boston"
    subject: str | None = None   # optional scope/context, e.g. "email tone"
    evidence: list[str] = []     # interaction/episode ids, carried into provenance
    created_at: datetime         # tz-aware (normalised to UTC)
```

Two deliberate scoping choices:

- **`memory_kind` targets the right typed record.** A correction is not always a
  preference — "my office is in Boston, not New York" is a `SemanticMemory`
  correction. Carrying the target kind lets the processor build the correct
  record type (ADR-0005's typed model) instead of forcing everything into
  `PreferenceMemory`. `kind` (correction vs. fresh preference) is orthogonal: it
  captures *intent*, `memory_kind` the *record type*.
- **Only explicit, memory-affecting feedback is modelled here.** A flat
  `content` string cannot soundly represent a `RATING` (its score and scale) or
  implicit signals (`REPEATED_CHOICE`'s alternatives and counts), so those are
  **not** in this contract. They are deferred to a follow-up ADR that gives them
  proper payloads — likely turning `FeedbackEvent` into a discriminated union, an
  ADR-backed breaking change. Modelling them now with an unfit field would be a
  false promise (a `RATING` with nowhere to put the rating).

> **Amended by ADR-0122 §1 (2026-08-09).** `memory_kind` becomes
> `MemoryKind | None`, defaulting to `None`, and absent means "resolve it from
> what this feedback touches" rather than "the caller could not decide". The first
> bullet's reason stands and is the amendment's own ground: because a correction's
> record type varies with what it corrects, a caller that cannot see the target —
> `interfaces/cli.py`, which had been filling the field from a fixed
> `CORRECTION → SEMANTIC` table — must be allowed to decline it. **The resolution
> is gated on `kind`, and only a correction is looked up**: `orchestration`
> resolves an absent value on a `CORRECTION` with one ranked read **scoped to
> ADR-0122 §3's fixed resolution set** — `PREFERENCE` and `SEMANTIC`, the kinds
> §4's processor below mints — and on a `PREFERENCE` with no read at all, to
> `PREFERENCE`, since a stated preference establishes one by its own intent and
> searching for it would file the user's preference wherever the store's nearest
> neighbour happens to live. Either way §4's mapping below receives a `MemoryKind`
> and is unchanged. A value the caller *does* supply is authoritative and
> suppresses the read. The second bullet is untouched. **ADR-0122 §3 is the
> operative text**; this note records the amendment and is not a second statement
> of its terms — where the two differ, ADR-0122 governs, and §6's deferral being
> taken up amends its resolution set there.

### 2. `FeedbackProcessor` — feedback in, proposals out

`core/protocols.py` gains:

```python
class FeedbackProcessor(Protocol):
    async def process(self, event: FeedbackEvent) -> Sequence[MemoryUpdateProposal]: ...
```

It returns zero or more proposals (zero for a kind it does not yet handle). It
does **not** ingest — the returned proposals flow to `MemoryIngestor` via the
pipeline, keeping `learning` dependent only on `core`. `process` is `async`
because a future model-backed processor is I/O-bound.

### 3. Learning produces proposals; the pipeline closes the loop

`learning` never imports `memory`'s concrete ingestor. The full loop —
`FeedbackEvent → process → MemoryUpdateProposal → MemoryIngestor → MemoryStore`
— is wired by `orchestration` (a later slice). Until then it is demonstrated by
an integration test that composes the real processor and the real ingestor, so
the vertical is proven before it is automated.

### 4. First processor: deterministic, user-asserted, typed by `memory_kind`

The first implementation, `RuleBasedFeedbackProcessor`, builds a `MemoryRecord`
of the event's `memory_kind` from its `content`:

- `PREFERENCE` target → `PreferenceMemory(preference=content, context=subject)`.
- `SEMANTIC` target → `SemanticMemory(fact=content)`.
- `PROCEDURAL`/`EPISODIC` targets return **no** proposal yet — they need more
  structure than a single content string (steps; an event time), so they are
  deferred rather than filled with degenerate data.
- **Provenance is `USER_ASSERTED`, confidence 1.0.** The user told us directly,
  so `DefaultMemoryPolicy` accepts it outright — which is what makes the loop
  "take" on the first correction (the roadmap's "policy accepts it"). `evidence`
  and `created_at` populate the provenance; ids come from an injectable factory
  and the timestamp from an injectable clock, for deterministic tests.

No natural-language interpretation happens here: the processor wraps
*already-structured* explicit feedback. Turning freeform feedback ("be less
formal") into a structured record is the job of a later model-backed processor
behind the same Protocol.

### 5. Known interaction with the policy (not resolved here)

Because `DefaultMemoryPolicy` returns `ACCEPT` for a user-asserted proposal
*before* its merge rule (ADR-0005 §3), an explicit correction that conflicts with
an existing **inferred** memory is stored as a *new* record rather than
superseding the stale one. The first loop ("learn a new preference, reuse it")
is unaffected, but "a correction supersedes a wrong belief" would leave the old
memory lingering. Refining the policy so an assertion supersedes a conflicting
inference is a **memory-policy** decision (a follow-up to ADR-0005), deliberately
out of scope here; this ADR only records the interaction.

### 6. Deferred

- **`RATING` and implicit feedback** (`REPEATED_CHOICE`, `IGNORED_SUGGESTION`) —
  a follow-up ADR gives them proper payloads (likely a `FeedbackEvent`
  discriminated union) once `orchestration` emits them; they will carry
  `OBSERVED`/`INFERRED` provenance with computed confidence, not 1.0.
- **`PROCEDURAL`/`EPISODIC` correction targets**, which need richer structure
  than `content`.
- **A model-backed processor** for freeform feedback, behind the same Protocol.
- **Assertion-supersedes-conflict** policy refinement (§5).

## Consequences

- **The first learning loop becomes real:** an explicit correction turns into a
  durable preference the system reuses — demonstrated now, automated once
  `orchestration` lands.
- **New `core` surface:** `FeedbackEvent`, `FeedbackKind`, and the
  `FeedbackProcessor` Protocol. `learning` depends only on `core`.
- **Propose/dispose is preserved end to end:** learning proposes, the existing
  policy disposes, the store persists — no subsystem writes memory directly.
- **The contract models only what it can soundly represent today** — explicit,
  memory-affecting feedback — rather than declaring `RATING`/implicit kinds it
  cannot yet carry. Adding those later is a known, ADR-backed change (a likely
  discriminated union), not a silent trap.
- **Revisit when** `RATING`/implicit signals need a home, a model-backed
  processor is added, or the assertion-supersedes-conflict policy question is
  taken up.
