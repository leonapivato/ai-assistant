# 320. The clauses left standing over the residue lanes' removed members and types retire, and the reading-level write path retires

- Status: Accepted
- Date: 2026-10-14
- Scope: the phases after understanding, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): the records [#3018](https://github.com/leonapivato/ai-assistant/issues/3018) asks for, for the ratified clauses that bind the `core` members and types the residue lanes removed after ADR-0319's survey, and the decision [#2685](https://github.com/leonapivato/ai-assistant/issues/2685) asks for on its `MemoryWriter` half.
- Dependency: [ADR-0294](0294-readers-no-longer-ingest-into-memory-and-what-they-wrote-stays.md), [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md) and [ADR-0319](0319-the-decisions-the-cutover-left-standing-over-deleted-code-retire-the-stamp-drops-recalls-limit-and-an-unasked-memory-question-is-logged.md), all Accepted.
- Authorization: the dispatcher assigned 0320 and authorized ratifying this decision once its reviews are green. §3 records the owner's ruling of 2026-10-14 on [#3039](https://github.com/leonapivato/ai-assistant/issues/3039)'s fourth item, and §4 the owner's ruling of 2026-10-14 on [#3042](https://github.com/leonapivato/ai-assistant/issues/3042). §2 is the dispatcher's ruling on #2685's `MemoryWriter` half, and §5 and the records of [#3041](https://github.com/leonapivato/ai-assistant/issues/3041)'s clauses are the dispatcher's rulings.
- **Changes `core`: §2 removes a `Protocol` member, `MemoryWriter.ingest_reading`, a breaking change under golden rule 5, and §5 removes the `TimeWindow` type.** §3 removes the email reader's six `Settings` fields. Nothing the wire carries changes, since neither `MemoryWriter` nor `TimeWindow` is reachable from `AssistantEngine`'s surface. The records of §6–§8 change no code: the members and types they concern left `core` in the residue lanes under ADR-0309 §5:1, or the code they govern was deleted at the cutover.
- **Supersedes**, each whole (§8): ADR-0041, ADR-0064, ADR-0115, ADR-0226 and ADR-0240.
- **Partially supersedes**, in the clauses §8's second table names: ADR-0008, ADR-0014, ADR-0026, ADR-0037, ADR-0039, ADR-0049, ADR-0084, ADR-0085, ADR-0086, ADR-0096, ADR-0097, ADR-0110, ADR-0117, ADR-0125, ADR-0140, ADR-0147, ADR-0152, ADR-0173, ADR-0177, ADR-0178, ADR-0181, ADR-0184, ADR-0194, ADR-0217, ADR-0228, ADR-0230, ADR-0231, ADR-0233, ADR-0235, ADR-0237, ADR-0238, ADR-0241, ADR-0247, ADR-0260, ADR-0273, ADR-0275, ADR-0279, ADR-0283, ADR-0294 and ADR-0297.
- **Defers**, superseding nothing (§4): ADR-0101's two subject operations and the clauses that specify them.

## Context

**What obliges it.** ADR-0319 recorded the decisions whose code the cutover deleted,
surveyed at `5bffba96`. It deliberately left standing every clause that binds a member,
type or store that survived in `core` then, even with no production caller, because a
record ahead of a removal would retire clauses over live code. #3018 lists those members
and types and asks that each be recorded when it leaves. A residue lane removes code under
ADR-0309 §5:1 and writes no ADR record, so the records fall to one sweep, as ADR-0319's
did.

**What the residue lanes removed.** Merged by `baaf50ff`:

| Lane | Pull request | What left `core` |
| --- | --- | --- |
| P1 | #3015 | Seven old-path Protocols, with `AuditTrail.pending_confirmation` and `resolution_of` |
| P2 | #3023 | The `ParkedReads` and `DeferralStore` Protocols, and `PlanStore`'s and `MemoryStore`'s old members |
| T1 | #3024 | The old path's types P1 left with no user, `ReplyChunk` among them |
| R3a, R3b, R3c | #3026, #3028, #3031 | The plan stores' old members and tables, and `planning/goals.py`, `planning/execution.py` and `planning/effects.py` |
| P3 | #3032 | The five goal-authorization Protocols, with their contracts and fakes |

Built and merging, in this order, ahead of this decision (§1:2):

| Lane | Pull request | What leaves `core` |
| --- | --- | --- |
| T3 | #3034 | ADR-0318's set, with `TurnOutcome`, `StepOutcome` and `RoutedOperation` |
| P4 | #3035 | ADR-0313 §3:3's delivery report and §5:4's members, and twelve errors no code raised |
| T2-outer | #3036 | The turn, routing, park, confirmation, question, goal-authorization and deferral types, and `ActionRequest`'s goal fields |
| T2-inner | #3037 | The goal, plan, step, attempt, evidence and read-ask types, and `PlanExport`'s seven old sections |
| P5 | #3038 | `MemoryStore.select` and four `search` axes, `ConversationLifecycle.history`, `CurrentContext` and `TimeOfDay`, and the turn's supply filter |

**The sweep.** Every name defined in `core` at `5bffba96` and not at `54506b6f`, the
top of that stack, was listed. Every ADR numbered below 0320 whose status is not already
wholly superseded and whose text names one of them, or names `ConversationLifecycle`'s
history or the supply filter, was read clause by clause where it is marked and section by
section where it is not. A clause retires here when the whole of what it obligates,
constrains or describes left with that set, or with the code the same lanes removed beside
it in `planning/`, `permissions/`, `memory/` and `orchestration/`. A clause that also
governs something that survives stands, its removed limb binding nothing (§7:2), and so does
every clause binding what the owner's authority milestone reuses or redoes:
`EgressBinder.rebind`, `ActionPolicy.resolve`, `ThresholdActionPolicy`,
`PermissionDecision.authorises` and `from_confirmation`, `RecipientGrant.established_from`,
`DestinationTrustStore.trust_of`, `UserConfirmation` and its honouring, and
`AuditTrail.open_invocations`. Voice's speech seams (ADR-0313 §3:7) and the facet readers,
which P5 kept ([#3039](https://github.com/leonapivato/ai-assistant/issues/3039)), stand as
well. What ADR-0309's §5 list, ADR-0313, ADR-0318 and ADR-0319 already record is not
recorded again.

**The reading-level write path.** ADR-0294 retired readers' scheduled ingestion into
memory, the one caller of `MemoryWriter.ingest_reading`, and kept the member and the
absence reconciliation it performs "with no caller, until a decision of their own retires
them" (ADR-0294 §2:3). ADR-0294's implementation has merged and nothing in production calls
the member; `tests/world/m23_harness.py`'s `PriorIngestion` replays prior ingestion through
it. P5 built the member's removal and held it on that clause, parked as `6665e18c`.
#2685 splits the surface in two. The `MemoryWriter` half is the member, `MemoryIngestor`'s
and the canonical fake's, their conformance cases, the `memory_ingest_reading` trace seam
and the reconciliation, and it is due now. The coverage half, `SourceReading.coverage` and
`ReadCoverage`, belongs with the readers' channels: a periodic check for changes that has to
notice a deleted entry may want exactly what coverage declares (ADR-0292 §6:12, §13:3).

The seam is named in ADR-0119 §8's unmarked prose and in ADR-0120's Context, and neither
binds: in a marked ADR unmarked text supplies no obligation (ADR-0089 §3:1). Neither ADR
carries a clause to retire, so §2:3 retires the seam itself. ADR-0115 decided the member,
and every clause of it still in force binds the member, so it is superseded whole.

**Email as a grantable source.** ADR-0140 made the email store a grantable source and
built a reader over it, read by two consumers: the request-path facet and the scheduled
ingestion. ADR-0318 retired the `FACET` use and ADR-0294 retired ingestion, so a grant
on email does nothing. The composition root still builds one email reader, and nothing
reads through it; it is the only holder of email's grantable identity (#3039). The owner
ruled on 2026-10-14 that email leaves the grantable sources and returns when the channel
model designs an email capability. At `54506b6f`, nothing but that facet reader uses
`EmailReader`.

**The subject operations.** ADR-0101 decided two `MemoryStore` operations over a stated
subject, a scoped `export` and `delete_about`, and held their triad until the first
surface that offers them (ADR-0101 §7:3). No surface came, so neither was built (#3042).
The owner ruled on 2026-10-14 that they wait for the owner's forgetting design, which
designs subject erasure over stories and people. Holding them longer contradicts no
sentence of ADR-0101, which already held them, so it is recorded as a deferral rather
than a supersession. ADR-0225's cascade, which leaned on `delete_about`, was superseded
whole by ADR-0287 and binds nothing to defer.

**The label index and `TimeWindow`.** `memory/sqlite_store.py` keeps a `record_labels`
index that P5's removals left written and never read (#3039). It was the storage ADR-0237
§9's fourth item left to its implementing lane, and that item is unmarked prose, so no
clause decided the index. `TimeWindow` was `occurred_within`'s argument and has no other
use.

**Clauses over code the cutover deleted (#3041).** The sweep found clauses that stand
only over code deleted before `5bffba96`, outside ADR-0319's record. ADR-0319 §3:3 asks
for an issue and a later record. Each was checked clause by clause, and the ones that
hold are recorded here (§8). ADR-0154 §4:1 does not hold: it binds the designated egress
seam, which survives. Its Condition 12 attestation rested on `StepExecution`, but that
attestation is unmarked prose, and whether the phases' activation-effect claim (ADR-0306
§6) restores the property is the authority milestone's question.

## Decision

We will supersede the decisions whose every clause still in force governed members, types
or code the residue lanes removed, and the clauses of others that did; keep every clause
that governs what survives; retire `MemoryWriter.ingest_reading` with the absence
reconciliation, keeping the coverage a reading declares for the readers' channels; take
email out of the grantable sources; defer ADR-0101's subject operations to the forgetting
design; and retire the label index and `TimeWindow`.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the dispatcher's authorization to ratify stands.

> **Normative.** This decision merges only after the residue lanes the Context's second
> table names have merged, since a record ahead of a removal would retire clauses over
> live code.

> **Normative.** §2's change lands in one lane after this decision has merged
> `Accepted`: `MemoryWriter.ingest_reading` leaves the `Protocol`, `MemoryIngestor`, the
> canonical fake and the conformance suite in one change, with the reconciliation, the
> trace seam and their tests, and `tests/world/m23_harness.py`'s `PriorIngestion` is
> reworked in the same change so that no test reaches the member. §5's label index and
> `TimeWindow` leave in the same lane.

> **Normative.** Each clause §2, §3 or §5 retires keeps binding the code it governs until
> the lane that removes that code merges, and no lane builds on it meanwhile.

### 2. The reading-level write path retires

> **Normative.** `MemoryWriter.ingest_reading` leaves the `MemoryWriter` Protocol, with
> `MemoryIngestor.ingest_reading`, the canonical fake's member and the
> `MemoryWriterContract` cases that pin it. `MemoryWriter.ingest` is unchanged.

> **Normative.** The absence reconciliation retires with it. Nothing closes a belief's
> validity window on its absence from a reading, and no implementation selects absence
> candidates or closes a window on what a reading's coverage declares.

> **Normative.** The `memory_ingest_reading` trace seam retires with the member, with the
> metric keys only that seam emits. A `MEMORY_WRITE` trace for `MemoryWriter.ingest` is
> unchanged (ADR-0119 §8:1, §8:3).

> **Normative.** The coverage half stays as it is, with no consumer, until the decision on
> the readers' channels keeps or retires it (#2685): `SourceReading.coverage`, `ReadCoverage`
> with its containment test, and the coverage the calendar reader declares (ADR-0110 §2,
> ADR-0117 §5).

> **Normative.** `Attestation.extent` with `ReportedExtent`, and the extent the calendar
> reader declares (ADR-0117 §2 and §6), stay as they are. The upcoming-event producer keeps
> reading it as ADR-0132 §3:2 and §5:1 decide.

> **Normative.** The retirement reaches nothing `MemoryWriter.ingest` does. `memory/ingest.py`
> keeps honouring a `UserConfirmation` as ADR-0319 §6:2 decides, and its policy, conflict
> search and trace are unchanged.

> **Normative.** A later decision that lets a reading close a belief's validity window on
> its absence decides that mechanism whole, and the clauses this section retires do not
> bind it.

### 3. Email leaves the grantable sources

> **Normative.** Email is not a grantable source. The composition root registers no email
> reader, `grantable_sources` offers no `"email"`, and no grant names it.

> **Normative.** The final cleanup lane removes, under ADR-0309 §5:1, the email facet
> reader the composition root builds, email's grantable identity (`_configured_email_location`
> and `_held_sources`' email arm), `EmailReader` with `readers/email.py`, and the six
> `email_*` `Settings` fields only the reader reads.

> **Normative.** `EmailFacet` and `SourceReading.facet`'s discriminated union stay as they
> are, and this decision changes no `core` type for email.

> **Normative.** Email returns only through the channel model's design of an email
> capability, which decides its reading, its grant and its configuration whole. The clauses
> §8 retires from ADR-0140 do not bind it.

### 4. ADR-0101's subject operations wait for the forgetting design

> **Normative.** ADR-0101 §1's two operations, `MemoryStore.export`'s `about_person` scope and
> `MemoryStore.delete_about`, and every clause of ADR-0101 that specifies them (§1:4,
> §2–§8) are deferred to the owner's forgetting design. That design decides whether they are
> built as ADR-0101 states them, changed or replaced, and no lane builds either before then.

> **Normative.** The deferral supersedes nothing. ADR-0101 §1:3 and §1:5 stand as written,
> and ADR-0100 §6's reservations stay unlifted while the operations wait.

> **Normative.** ADR-0101 keeps `Accepted` and records the deferral on its status line and in
> a dated header note, atomically with this ADR under ADR-0070 and ADR-0082.

### 5. The label index and `TimeWindow` retire

> **Normative.** The `record_labels` index in `memory/sqlite_store.py` retires, with its
> writes, its migration and `memory/reembed.py`'s carrying and verification of it. No read
> queries it since `MemoryStore.select` and `search`'s person and topic axes left, and the
> subject query that was its last planned reader waits (§4).

> **Normative.** No migration is written for a store that holds the table (ADR-0309 §6:4).

> **Normative.** `TimeWindow` leaves `core/types.py`, since its one use was `search`'s
> `occurred_within` axis.

### 6. What retires whole

> **Normative.** The decisions §8's first table names are superseded whole: every clause of
> each still in force governed only members, types or code the residue lanes removed, or
> the reading-level write path §2 retires.

### 7. What retires in part

> **Normative.** Of each decision §8's second table names, the clauses that table names are
> superseded, and every other clause of that decision stands. Its rows marked (#3041) govern
> code the cutover deleted, and its row for ADR-0140 governs the code §3 removes.

> **Normative.** Where a clause that stands names a removed member, type, error, store table
> or module as one of several things it governs, that limb binds nothing and the rest of the
> clause binds as written. No record is written for such a limb.

> **Normative.** A clause this decision does not name stands as written. A lane that finds
> another clause standing only over removed code files an issue, and a later ADR records it.

> **Normative.** Where a retired clause's subject is authority (a confirmation, a goal's
> authorization, a quote, a parked read), it retires because its code is gone, and the
> owner's authority milestone redoes the subject. Nothing here decides how, and every clause
> binding a member or type that milestone reuses stands.

### 8. Relationship to earlier decisions

Superseded whole (§6):

| Earlier decision | What it governed |
| --- | --- |
| ADR-0041 | The `PENDING → SKIPPED` edge on `APPROVAL_DENIED` in `PlanExecution`'s transition table, with `SkipReason` and `StepTransition` |
| ADR-0064 | `SqlitePlanStore`'s execution ordinal: `exec_counter`, its high-water mark and `created_seq`, with their checks at open and at every allocation |
| ADR-0115 (§2) | `MemoryWriter.ingest_reading`: its signature, its serialisation across a covered reading, its arms without a coverage, its observation of the reading, its conformance cases and its triad |
| ADR-0226 | What ADR-0319 left, §4: `ReadKind`, `ReadAsk`, `ReadRequest` and `ActionPlan.read_request`, `PlanExport`'s move for them, and a read ask never driven as a plan step |
| ADR-0240 | What ADR-0319 left, §2:1–§2:4, §2:6 and §11:3: `StructuredAsk`, `ReadAsk.structure` and its validator arm, and the `PlanExport` move that carried the ask in a plan |

Superseded in part (§7); every clause the middle column does not name stands:

| Earlier decision | What retires | What it governed |
| --- | --- | --- |
| ADR-0008 | §1, §4's sentence adding `ContextError` with its third bullet, and §6 | `CurrentContext`, `TimeOfDay`, `ContextError` and the facets §6 deferred onto `CurrentContext`, which left `core`; §4's first bullet and §5's `timezone` stand |
| ADR-0014 | §2; §3; §4, in what ADR-0319 left of it; §5's plan and execution members, its transitions-not-snapshots rule, its compare-and-swap, `PlanExport`'s `goals`, `plans` and `executions` with their closure rule, `clear`'s refusal while a step is live and its `active_executions` paragraph; and §7's bullets on output references, idempotency keys, execution leases, step dependencies, `approval_ref` and goals in memory | `ActionPlan`, `PlanStep`, `ExecutionState`, `StepExecution`, `StepStatus`, `SkipReason` and `StepTransition`, `planning/execution.py`, and `PlanStore`'s plan and execution members; `PlanStore` with its surviving members, local residency, `export`, `clear`'s erase and retention stand |
| ADR-0026 | §4's `context` → `ContextError` bullet, and its paragraphs on the context source, from "For `context` this is the substantive clause" to the two tests they oblige | `ContextError` with `ClockContextSource`'s `required` marker and `AssemblingContextProvider._safe_contribute`; §4's other translations and §5's ordering stand |
| ADR-0037 | §2's two paragraphs reading the step through `PlanStore.get_plan` and the execution through `PlanStore.get_execution` | `PlanStore.get_plan` and `get_execution`, with `PlanStep` and `ExecutionState`; §2–§3's decide, record and read back stand |
| ADR-0039 | §1–§5; §7's bullets on `abandon_running` and on recovery not reading `kind`; §8; and §10 but its `PlanExport.schema_version` bullet | `StepFailure`, `StepExecution.failure` and `StepTransition.failure`, `planning/execution.py` and the plan stores' step cases; §10's `PlanExport` version rule stands |
| ADR-0049 | §1's `plans` and `executions` tables, their foreign keys, the `version`, `active` and `created_seq` columns and the rules over them, and the read-check-write paragraph's `commit_transition`, `start_execution`, `save_plan` and live-step `clear` limbs; §2; §3; and §5's bullets but its newer-schema refusal | `SqlitePlanStore`'s plan and execution tables, its execution-id nonce and ordinal, and its recovery of executions after a crash; §1's `meta` table and schema refusal stand |
| ADR-0084 | §4's three bullets placing `Disposition`, `QuestionState` and `SuccessorLink` in the closure, with its paragraph that relocating those enums is not redefining them; and §8, in what ADR-0319 left of it | `Disposition`, `QuestionState` and `SuccessorLink`, which left `core`; §4's closure rule stands |
| ADR-0085 | §4's rows for `ContinuationToken`, `Confirmation`, `StepOutcome`, `TurnOutcome`, `QuestionState`, `Retirement`, `SuccessorLink`, `Question`, `AnswerKind`, `AnswerOutcome`, `Disposition` and `TurnResult`; §4b's `StepOutcome` and `AnswerOutcome` rows, its paragraph on `StepOutcome`'s invariant and its paragraph on relocating the enums; and §5's walk from `TurnOutcome`, `Question` and `AnswerOutcome`; each in what ADR-0319 left of it | The turn-surface and deferred-question types, which left `core`; the belief and conversation types, §4c's encodability rule and §6 stand |
| ADR-0086 | §1's paragraph that the evidence bound does not reach `Goal`, with its two bullets | `Goal.provenance` on `PlanStore.save_goal`'s path; the bound on `MemoryRecord` stands |
| ADR-0096 | §1:1 and §4:1 | `CurrentContext`'s optional facet fields and their presence in an assembly; the facets on `SourceReading` stand |
| ADR-0097 (#3041) | §5a:6 | An ingestion pass over a source with no live `INGEST` grant, which ADR-0294 retired |
| ADR-0110 (§2) | §3, §4, §5 and §5a | The absence reconciliation `MemoryWriter.ingest_reading` performs over a covered reading: when an absence closes a window, what absence is, the close's obligations and its serialisation; §1, §2's coverage, §7 and §8 stand |
| ADR-0117 (§2) | §3:1–§3:3, §9:2 and §9:3 | ADR-0110 §3's containment judged against the extent in both `MemoryWriter` implementations, and the writer suite's and implementations' tests of it; the extent (§2, §6), the calendar's coverage (§5), §4, §8:1, §9:1 and §9:4 stand |
| ADR-0125 | §10:1 | `DeferredProposal`'s refusal of a `DataTier.SECRET` proposal and the deferral queue, which left `core` |
| ADR-0140 (§3) | §1–§5, §7, §9–§11 and §12, and §13:2 but its test that the facet union discriminates at validation, each in what ADR-0294 left of it | The email source: `EmailReader` and its store, its proposals, its grant as a grantable source, its settings and its lanes' obligations; §6's `EmailFacet` and facet union, §13:1 and §13:2's test of that union stand |
| ADR-0147 | §6:7 | `StepExecution.output` as a projection carrying content with no origin; §6:1–§6:6 stand |
| ADR-0152 | §9:6 and §13:22 | `Disposition.EGRESS_UNBINDABLE` and its cases; `EgressBinder`, its refusals and the store-outage case stand |
| ADR-0173 | §2:2, in what ADR-0296 left of it, and §4:3 | `ReplyChunk` on a reply stream, and the mapping of `converse_streaming`'s yielded union onto the frames; the `CHUNK` frame kind, §4:5's reflection rule and what ADR-0319 left of §§10–12 stand |
| ADR-0177 | §8:1, §8:2, §8:9 and §8:10 | A browser surface answering a `Confirmation`: its precondition and its no-claim floor; the authority milestone redoes asking the user |
| ADR-0178 | §1:1–§1:2; §2:1, in what ADR-0181 and ADR-0233 left of it, and §2:2–§2:4; §3:1–§3:11; §4:1–§4:3; §6:1–§6:3; §8:1–§8:4; §9:1–§9:3 and §9:6–§9:7 | `Confirmation.egress`, `ConfirmationEgress` and `ConfirmationDestination` with its derived set, their `PROTOCOL_VERSION` move and size, and the discharge of ADR-0177 §8; §7 and §11 stand |
| ADR-0181 | §6:1–§6:7 and §10:7 | Rendering `planned_with_external_content` on a `Confirmation`'s `ConfirmationEgress`, and its test; the field on `EgressBinding`, `rebind`, `authorises` and §5 stand |
| ADR-0184 | §8:2 | The bar on a `ConfirmationEgress` for a row whose origin is unrecorded; §8:1 and §8:3 stand |
| ADR-0194 | §6:8 | What the ceiling adds to a `Confirmation` and its card, which are gone; the ceiling, `SpendLedger` and §4:7's refusal window stand |
| ADR-0217 | §7:19 and §7:20 | `RoutableOperation`'s `GUARD` and `UNGUARD` members and their routed path; `AssistantEngine.guard` and `unguard` stand |
| ADR-0228 | §5:1, §5:5, §5:6, §5:12, §6:1, §6:2, §12:4 and §12:7 | `ActionPlan.supersedes`, `PlanStore.save_plan`'s refusal of an unresolved one, `PlanExport`'s closure over plans and its move, and `ActionPlan` on the turn's outcome; §6:3 stands |
| ADR-0230 | §1:1–§1:3, §12:2 and §12:4 | `ReadKind.LOCAL_FILE`, `ReadAsk.entry`, `ReadRequest`'s one ask per kind, and the `PlanExport` move for them; the `Fetcher` seam, the listing types, §1:4 and §12:3 stand |
| ADR-0231 (#3041) | §1:1–§1:3, §6:4, §9:1, §16:6 and §16:7 | `ReadKind.WEB_SEARCH` with its `ReadAsk` and `ReadRequest` arms, a search decision's empty `step_id` and `execution_id`, the version moves for them, and the servicing of a `WEB_SEARCH` ask on a recorded `ALLOW` under `SearchDisposition`; the `WebSearcher` seam, §1:4, §9:4, §9:5, §14 and §17:4 stand |
| ADR-0233 | §4:7, §8:1–§8:11, §11:1, §15:3 and §15:8 | `ConfirmationEgress.coverage` and its version move, and the floor for a surface rendering a `Confirmation`; `SpanCoverage`, `EgressBinding.coverage`, §9, §10 and §11:3–§11:6 stand |
| ADR-0235 | §4:3, §4:4, §4:9–§4:12, §12:3, §12:4, §12:6, §12:7, §12:12–§12:15, §12:18 and §12:30 | `RecipientGrantOutcome`, `RecipientGrantNotEstablished` and `TurnOutcome`'s grant outcome, with their tests and `UngrantableActError`'s; `PermissionDecision.from_confirmation` (§4:13–§4:17) and the grant refusals stand |
| ADR-0237 (§5) | §1:1–§1:3, §2:1, §2:2, §2:4, §3:1–§3:4, §4:1, §4:3, §4:4, §5:1–§5:3, §6:2, §6:3, §7:1, §7:2, §7:5, §8:1, §8:2 and §9:1–§9:3 | `MemoryStore.select` and `search`'s `occurred_within`, `participants`, `topics` and `about_person` axes, with `TimeWindow` and their matching, order, window and conformance cases; `search`'s shape and `limit`, §2:3, §6:1, §7:3, §7:4 and §8:3 stand |
| ADR-0238 (#3041) | §3:1, §14:7, §15:2–§15:7 and §15:10–§15:25 | The record-level exclusion from a `SearchSupply`, the composer's prompt, and the arms over the composer, the servicing path and the conversation's search budget; `Placement.reach`, the trust store, §3:2–§3:3, §15:8–§15:9 and §15:26–§15:29 stand |
| ADR-0241 (#3041) | §12:8–§12:11 and §12:14 | The arms over the turn's servicing path: the two-turn and within-turn replies, the three-bounds arm and the fault at the send's disposition; the `WebSearcher` arms stand |
| ADR-0247 | §7:3–§7:5 and §12:11–§12:13 | What `rebind`'s transcription does to a `ParkedRead`, and the arms over the parked read's answer; §7:1–§7:2, §8:5 and §9:1 stand |
| ADR-0260 | §2:1, §2:2 and §3:1 | `ReadKind.FORECAST_READ` with `ReadRequest`'s and `ReadAsk`'s arms for it; the `Forecaster` seam, §2:3, §3:2–§3:3 and the arms stand |
| ADR-0273 | §3:3 and §3:4 | The booking's place in the `OutboundDestination` vocabulary, which left `core` with `Disposition` and `StepStatus`; the declarations and §3:1–§3:2 stand |
| ADR-0275 | §8:8, in what ADR-0283 left of it | The old conversational methods' recording-loss carriers, `TurnOutcome.capture_degraded` and `resume`'s result |
| ADR-0279 | §2:1–§2:8 | The `RoutingRecorder` and `RoutingTrail` Protocols, with `RoutedOperationRecord` and `RoutingTrailError`; §3's `guard` and `unguard` stand |
| ADR-0283 | §3:3, §4:1 in what ADR-0293 left of it, §5:1 and §10:1 | `MemoryStore.episode_parking`, `ConversationLifecycle.history`'s read and its pairing with `deliveries`, and a resume's conversation through its parking episode; the channel reads, deletion, reclaim and the observer stand |
| ADR-0294 (§2) | §2:3 and §3:2 | The keep clause for `MemoryWriter.ingest_reading` and its reconciliation (§2:3, ADR-0320 §2), and a question parked from an ingested proposal, whose queue is gone (§3:2); the readers, their coverage, §3:1, §3:3, §4 and §5 stand |
| ADR-0297 | §2:1, §2:3, §2:4 and §2:9 | `StepTransition.activation_id`, the step claim's naming rule, `PlanStore.commit_transition`'s stop conjunct and `StepExecution`'s non-field; `record_stop`, `PlanExport.stopped_activations`, `ClaimStopped` and §§3–5 stand |

| Earlier decision | What changes |
| --- | --- |
| ADR-0309, ADR-0313, ADR-0318, ADR-0319 | Nothing: each already records what it retires, and nothing of it is recorded again |
| ADR-0276 §5:2, ADR-0281 §6:2–§6:3, ADR-0284 §2:4, ADR-0286 §3:3, ADR-0308 §7 | Nothing: ADR-0318 §8 ruled their resume and routed limbs |
| ADR-0200, ADR-0274 | Nothing: ADR-0293 and ADR-0313 decided what of the typed and spoken conversational paths retires, their `TurnOutcome`, `ReplyChunk` and history limbs included |
| ADR-0119, ADR-0120 | Nothing: they name the `memory_ingest_reading` seam only in unmarked prose, which binds nothing (ADR-0089 §3); §2:3 retires the seam |
| ADR-0116, ADR-0164 | Nothing: `ingest_reading` is named only in prose, or as one crossing of a write trace among others |
| ADR-0183 §2:2 and §6 | Nothing: what a reader declares of its coverage is the half §2:4 keeps |
| ADR-0106, ADR-0130, ADR-0131 | Nothing: `UserConfirmation`'s honouring and the notification stores survive; a deferral type named as a shape is a limb (§7:2) |
| ADR-0145 §4 and §7:4, ADR-0152 §9:7 | Nothing: the selection stage's two causes and the binder's refusal survive under them; `Disposition` is a limb (§7:2) |
| ADR-0203, ADR-0204, ADR-0210 | Nothing: the subtraction on an unbounded pass survives at the phases' read sites, so the turn's supply filter leaving takes none of their standing clauses |
| ADR-0178 §7, ADR-0186 | Nothing: the history surface renders a recorded binding under them |
| ADR-0100, ADR-0101, ADR-0113, ADR-0129, ADR-0162, ADR-0163, ADR-0239 | Nothing: `about_person` and `participants` are fields of the record and survive; only `search`'s axes leave |
| ADR-0087 | Nothing: its vectors witness the encoding, and their tests no longer build a `Confirmation` |
| ADR-0223 §1:2 and §3:2 | Nothing: their property reaches the phases' origin stamp |
| ADR-0247 §6:9, ADR-0306 §4:11 | Nothing: they name removed types and Protocols beside what survives, as limbs (§7:2) |
| ADR-0101 | Deferred, not superseded (§4): §1's two operations and the clauses that specify them wait for the forgetting design; §1:3 and §1:5 stand |
| ADR-0225 | Nothing: ADR-0287 superseded it whole, so its §5 cascade over `delete_about` binds nothing to defer |
| ADR-0237 §9's fourth item | Nothing: it is unmarked, and it left the label index's storage to its lane; §5 retires the index |
| ADR-0154 §4:1 | Nothing: it binds the designated egress seam, which survives; its Condition 12 attestation is unmarked prose, and whether the activation-effect claim restores that property is the authority milestone's question |
| ADR-0189 §6:3, ADR-0199 §3:3 | Nothing: they name email or `EmailFacet` beside what survives, as limbs (§7:2) |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of each ADR this section's first two tables name, atomically with this
> ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- No ratified clause is left binding a member or type the residue lanes removed from
  `core`, so the corpus a reader consults describes the phases' surface and nothing of the
  old path's.
- P5b has the decision ADR-0294 §2:3 waited for, and removes the member, the label index
  and `TimeWindow` in one change.
- The cleanup lane removes a reader nothing reads and a grant that does nothing, so no
  surface offers the user a grant on email that changes nothing.

**What it costs.**
- No belief is closed on its absence from a source. One the user does not correct or
  forget stays what the source last reported, as ADR-0294 §3:3 already has it for every
  ingested belief.
- An open lane whose text cites a clause this decision retires is bound by it under
  ADR-0209 when this merges.
- A deployment that configured an email store loses it as a source until the channel
  model designs email; what it already wrote stays (ADR-0294 §3:1).

**What stays open.**
- The coverage half: whether `SourceReading.coverage` and `ReadCoverage` stay,
  for a channel that has to notice a deleted entry, is the readers' channel decision's
  (#2685).
- What the authority milestone reuses or redoes, with the clauses that bind it, ADR-0154
  §4:1's Condition 12 attestation among them.
- `EmailFacet`, which nothing produces once the reader leaves, and the facet union it
  sits in.
- Subject erasure and subject-scoped disclosure, which the forgetting design decides
  (§4).
- The prose in `src/` and the ADRs' own Context sections that still names a removed type,
  which the residue lanes list for the cleanup lane.

## Alternatives considered

- **Leave each record to the lane that removed the code.** Not possible: an implementation
  lane writes no ADR record (ADR-0309 §5:1), which is why #3018 asks for this one.
- **Record each lane's clauses in its own ADR.** Not chosen: five lanes in one stack would
  write five records over one corpus, each with its own reciprocal header records on many
  of the same ADRs, and one sweep reads the corpus once.
- **Keep `ingest_reading` until the readers' channel decision.** Rejected: no channel
  ingests a reading (ADR-0294 §1:2), so the member has no future caller to wait for. Only
  the coverage a reading declares might be wanted, and §2:4 keeps it.
- **Supersede ADR-0101's operations rather than defer them.** Not chosen: the forgetting
  design may build them as written, and ADR-0101 already held them until a surface.
- **Keep email grantable for a later capability.** Rejected by the owner's ruling: a grant
  that does nothing is a promise nothing keeps, and the channel model decides email whole.
- **Retire the coverage half with the member.** Not chosen: #2685 leaves it to the readers'
  channels, and the decision that might want it has not been made.
- **Keep ADR-0110 §3's conditions as a standing rule for a later absence mechanism.**
  Rejected: §3 and §4 define absence by what ingesting the reading's proposals returned,
  which no surviving path produces, and a later mechanism decides its own conditions
  (§2:7).
