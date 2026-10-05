# 294. Readers no longer ingest into memory, and what they wrote stays

- Status: Proposed
- Date: 2026-10-04
- Scope: [#2578](https://github.com/leonapivato/ai-assistant/issues/2578), the channel redesign: the retirement of readers' scheduled ingestion into memory that ADR-0292 §13 names, taken ahead of the readers' channels.
- Authorization: the owner ruled on 2026-10-04, in the review ADR-0292 records, that readers' scheduled ingestion into memory retires (ADR-0292 §13's table), and directed that it go now rather than wait for the readers' channel design. The dispatcher assigned 0294.
- **Supersedes** [ADR-0142](0142-each-ingestion-source-is-its-own-stage-its-own-operation-and-its-own-row.md) — **whole.** Every clause rules how an ingestion source is armed, staged, operated and reported, and none survives the stages (§1 below).
- **Partially supersedes** [ADR-0093](0093-a-sensor-reads-a-source-and-proposes-what-it-read.md) — **six scopes.** §3's memory as a reading's second consumer and ingestion's cadence; §6 entire; §7's and §7a's interval field (`calendar_sensor_interval`, spelled `calendar_reader_interval` in the code) and the states it makes with the path; §8's ingestion-side posture; §9's scheduled-ingestion clause; and §10's later-lane items for the ingestion stage, the `Engine` operation and the scheduler job. §1, §2, §4, §5, §7b, §11 and every other part of §3 and §7–§10 stand.
- **Partially supersedes** [ADR-0140](0140-the-email-source-is-a-file-the-fetcher-replaces-whole.md) — **four scopes.** §12:1's `email_reader_interval` row, §12:2 entire, §12:5's interval half, and §13:2's item for the ingestion wiring and its scheduler job. Every other clause stands.
- **Partially supersedes** [ADR-0133](0133-a-producers-read-is-a-third-use-of-a-source-and-the-user-grants-it-separately.md) — **two scopes.** §2:3's *any non-empty subset of the three*, for a new grant; and §6:6's help text naming all three. Every other clause stands.
- **Partially supersedes** [ADR-0139](0139-a-standing-grant-is-read-from-the-store-not-from-the-sources-the-hub-can-offer.md) — **one scope.** §3:2, in which members a surface offering uses for a new grant carries. Every other clause stands.
- **Partially supersedes** [ADR-0120](0120-a-measure-is-a-rate-over-the-trace-stream-read-offline-while-the-hub-is-stopped.md) — **one scope.** §3:2's `ingest` member of the machine set, which the code spells `ingest_calendar` and `ingest_email` under ADR-0142 §4. Every other clause stands.
- **Partially supersedes** [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md) — **one scope.** §Decision:2's and §13:1's hold on readers' scheduled ingestion until its replacement is built. §13:2, §13:3 and the rest of the table stand.

## Context

ADR-0292 §13 lists readers' scheduled ingestion into memory among the mechanisms
that retire, its function kept by "pulls when relevant and pushes for changes;
memory keeps what activations conclude". Its alternatives record why: the calendar
and the mailbox already hold their history, and a copy in memory goes stale. Its
§13:1 holds each retirement until the replacement is built. The owner ruled the
same day that this one goes now, without waiting for the readers' channels.

What the code holds, at `f163f34b`:

- **The jobs.** `service/scheduler.py` arms an `ingest_calendar` row when
  `calendar_reader_interval` is set and an `ingest_email` row when
  `email_reader_interval` is set. Both default to `None`, so neither runs unless an
  operator arms it.
- **The operations.** `Engine.ingest_calendar` and `Engine.ingest_email`, each over
  its own `IngestionStage` in `orchestration/ingestion.py` returning an
  `IngestionReport`. Each checks for a live `INGEST` grant, reads its own reader
  instance, and writes the reading through `MemoryWriteStage.write_reading` to
  `MemoryWriter.ingest_reading`. Neither is on `AssistantEngine`, so neither is on
  the wire.
- **The wiring.** `app/composition.py` builds a reader instance per consumer: for
  the calendar one for the facet, one for ingestion and one for the upcoming-event
  producer; for email one for the facet and one for ingestion.
- **The reporting.** `service/configuration.py` reports whether each job is armed
  and how often it runs, and `evaluation/_vocabulary.py` counts `ingest_calendar`
  and `ingest_email` in the machine seam set.
- **The grant use.** `GrantScope.INGEST`, "reading the source to propose beliefs
  into memory" (ADR-0097 §2), one of the three uses ADR-0133 §2:3 lets a grant
  name. `assistant grant` and `assistant amend` offer it, and the gateway offers it
  as "Durably remember what it says".

Two other consumers read the same sources and do not ingest. The request-path
facet reads at assembly time under `FACET` (ADR-0096, ADR-0140 §6), and is the
pull ADR-0292 §13:3 names. The upcoming-event producer reads the calendar under
`NOTIFY` and walks the reading's proposals (ADR-0132 §3), and is the push ADR-0292
§13:3 names. Neither derives anything from ingestion (ADR-0093 §3, ADR-0132 §3:1).

## Decision

We will stop readers writing what they read into memory now, keep everything else
a reader does, and leave what was already written where it is.

### 1. Ingestion retires now

> **Normative.** No job, engine operation or stage reads a source to propose what
> it read into memory: the calendar's and the email source's scheduled ingestion
> are retired.

> **Normative.** This ADR adds nothing in ingestion's place. A source's content
> reaches memory only as what an activation concludes, once the readers' channels
> build the pulls and pushes ADR-0292 §13 names.

> **Normative.** The retirement takes effect when this ADR's implementation lands,
> and does not wait for that replacement. ADR-0292 §Decision:2 and §13:1 no longer
> hold this mechanism in force; §13:2 binds the replacement when it is built.

Until then a deployment that configured a reader keeps what the facet and the
upcoming-event producer give it, and loses the rest. The facets carry counts and
instants and no entry text (ADR-0096 §6:4, ADR-0140 §6:2), so the assistant cannot
answer what an entry or a message says. The upcoming-event producer still states
each occurrence it notices in a sentence (ADR-0132 §3:2). Both readers ship
disabled (ADR-0093 §7, ADR-0140 §12:5), so a deployment that never armed one loses
nothing.

### 2. What stays

> **Normative.** The readers stay as they are: the `Reader` contract, the calendar
> and email readers, their path, window, cap and deadline settings, and what a
> reading carries, its proposals and coverage included.

What a reading carries is the readers' channels' to decide. The calendar's
proposals keep a consumer in the upcoming-event producer; the email reader's lose
their only one.

> **Normative.** The request-path facets and the upcoming-event producer stay,
> each on its own reader instance and under its own grant use, exactly as ADR-0096,
> ADR-0140 §6 and ADR-0132 decide them.

> **Normative.** `MemoryWriter.ingest_reading` and the reconciliation it performs
> stay, with no caller, until a decision of their own retires them
> ([#2685](https://github.com/leonapivato/ai-assistant/issues/2685)).

Removing `ingest_reading` is a Protocol change in the memory subsystem that owes
supersessions of ADR-0110, ADR-0115 and ADR-0117, and coverage may matter to a
periodic check for changes (ADR-0292 §6:12). Neither belongs in the removal of a
consumer.

### 3. What ingestion already wrote stays

> **Normative.** The retirement retires no belief, closes no validity window,
> deletes no record and alters no stored record.

> **Normative.** A question parked from an ingested proposal stays parked, exactly
> as any other parked question.

> **Normative.** Nothing reconciles an ingested belief against its source again.
> It stays what the source reported when it was last read, under its attestation
> (ADR-0092), until the user forgets or contradicts it.

This is ADR-0097 §6's answer to revocation, and its reasons carry over unchanged.
No operation retires every record from a source; closing the windows would record
that the system stopped believing a fact at the moment a mechanism was removed,
which says nothing about the fact; and deleting would fuse a removal with a
`forget` the user did not ask for. A stale belief stays legible as an old report,
because its attestation names its source and when that source reported it.

### 4. The `INGEST` use

> **Normative.** `GrantScope` keeps `INGEST`. A recorded grant naming it stays
> readable, exportable and revocable, and a surface rendering it names every use
> it names, `INGEST` included (ADR-0139 §3:3).

The grant store is append-only (ADR-0097 §4), so grants that name `INGEST` exist
and stay. ADR-0097 §6 relies on them: a belief ingested under one points at a
source whose grant history must still read as authorised.

> **Normative.** No implementation reads a source under `INGEST`.

> **Normative.** A new grant names a non-empty subset of `FACET` and `NOTIFY`.
> `AssistantEngine.grant` refuses a scope naming `INGEST` with `ValueError`,
> locally and before any I/O, as it refuses an empty one, and records nothing.

> **Normative.** `SourceGrant` keeps accepting `INGEST`, so a stored grant still
> loads and a revocation still transcribes the scope of the grant it revokes.

> **Normative.** No grant is revoked, narrowed or rewritten because it names
> `INGEST`. A live grant naming another use beside it stays live for that use.

ADR-0097 §8 forbids anything deciding on the user's behalf what they permitted.

> **Normative.** A surface offering the uses for a new grant, including an
> amendment's new scope, offers `FACET` and `NOTIFY` and not `INGEST`.

This keeps ADR-0139 §3:2's protection rather than breaking it: a surface offers
every use the hub accepts for a new grant, so no surface and the hub disagree about
the vocabulary. An amendment takes its new scope from that offer (ADR-0139 §4:6),
so it carries no `INGEST` forward and the refusal above is never its second act.

### 5. What the implementation owes

> **Normative.** The implementing change removes `Engine.ingest_calendar`,
> `Engine.ingest_email`, `IngestionStage`, `IngestionReport`,
> `MemoryWriteStage.write_reading`, the scheduler's two ingestion rows, the composition
> root's ingestion reader instances and stages, and their tests.

> **Normative.** It removes `calendar_reader_interval` and `email_reader_interval`
> from `Settings`, with the load-time refusals that pair each with its path.

> **Normative.** `service/configuration.py` reports no ingestion figure, and the
> machine seam set loses `ingest_calendar` and `ingest_email`.

A trace a store already holds under either seam is then read as unclassified,
exactly as ADR-0285 §7 left the observation seams.

> **Normative.** It makes `AssistantEngine.grant` refuse `INGEST` as §4 rules in
> the Protocol, the engine, the wire client and the canonical fake engine, with a
> conformance case, and drops `INGEST` from the CLI's and the gateway's offers.

> **Normative.** The change that makes `grant` refuse `INGEST` advances
> `PROTOCOL_VERSION`.

A frame an older client may send, a grant naming `INGEST`, is refused by the newer
hub, which is ADR-0124 §9:2's test in one of its two directions; the version then
says so at connect rather than inside a call.

`Settings` ignores an environment variable that names no field, so an environment
still setting `ASSISTANT_CALENDAR_READER_INTERVAL` or
`ASSISTANT_EMAIL_READER_INTERVAL` starts without an error and arms nothing. The
deploy after the change deletes them.

## Consequences

**What becomes simpler.** Nothing writes a reader's content into memory on a
timer, so no belief goes stale behind the user's back while the source moves on,
and the grant offer stops promising a use nothing performs. Two jobs, two
operations, two stages, two settings and one grant use leave the code paths a
change to memory or to a reader has to keep working.

**What it costs.** Until the readers' channels are built, a configured reader
contributes counts, instants and upcoming-event notices, and no entry or message
content. Beliefs ingested before the change stay and are never refreshed; the
user's remedy is `forget`. `MemoryWriter.ingest_reading` stands without a caller
until #2685 is decided.

**What follows.** The implementing lane (§5). #2685 for the reading-level write
path. The readers' channels, which ADR-0292 left open, decide the pulls and pushes
that keep this function and what a reading carries.

## Alternatives considered

- **Wait for the readers' channels**, as ADR-0292 §13:1 ruled. Declined by the
  owner on 2026-10-04: the mechanism is off by default and kept only until its
  replacement arrives.
- **Remove `INGEST` from `GrantScope`.** Declined: stored grants name it, and a
  grant store that can no longer load its own history breaks ADR-0097 §4 and §6.
- **Keep offering `INGEST`.** Declined: it promises remembering that nothing does.
- **Retire or delete what ingestion wrote.** Declined for ADR-0097 §6's reasons
  (§3 above).
- **Retire `ingest_reading` and coverage here.** Declined to keep this a removal
  of a consumer; #2685 carries both.
