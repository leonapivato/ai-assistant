# 319. The decisions the cutover left standing over deleted code retire, the stamp drops recall's limit, and an unasked memory question is logged

- Status: Proposed
- Date: 2026-10-14
- Scope: the phases after understanding, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): the records [#2836](https://github.com/leonapivato/ai-assistant/issues/2836) asks for, for the ratified decisions whose code the cutover's deletion lanes removed or are removing, and four decisions those deletions leave to be recorded.
- Dependency: [ADR-0309](0309-the-phases-are-built-beside-the-old-path-and-one-cutover-switches-the-controller-over-deletes-the-old-path-and-goes-live-in-one-deploy.md), ADR-0313 and ADR-0318, all Accepted.
- Authorization: the dispatcher assigned 0319 and authorized ratifying this decision once its reviews are green. §4 is the dispatcher's ruling on [#2989](https://github.com/leonapivato/ai-assistant/issues/2989), and §5 the dispatcher's ruling for the deferred-question store's deletion, the simple option the owner takes on deferred areas.
- Changes no `core` type or Protocol and nothing the wire carries. The seams whose implementations the cutover deleted leave `core` under ADR-0309 §5:1, in their own lanes; this decision records which earlier decisions stop binding when they go.
- **Supersedes**, each whole (§8): ADR-0022, ADR-0033, ADR-0034, ADR-0047, ADR-0051, ADR-0053, ADR-0055, ADR-0057, ADR-0058, ADR-0071, ADR-0158, ADR-0160, ADR-0170, ADR-0176, ADR-0201, ADR-0211 and ADR-0244.
- **Partially supersedes**, in the clauses §8's second table names: ADR-0008, ADR-0014, ADR-0028, ADR-0029, ADR-0037, ADR-0039, ADR-0042, ADR-0049, ADR-0052, ADR-0059, ADR-0060, ADR-0074, ADR-0083, ADR-0084, ADR-0085, ADR-0093, ADR-0096, ADR-0097, ADR-0106, ADR-0115, ADR-0119, ADR-0122, ADR-0144, ADR-0148, ADR-0150, ADR-0162, ADR-0173, ADR-0175, ADR-0177, ADR-0178, ADR-0181, ADR-0185, ADR-0187, ADR-0189, ADR-0192, ADR-0193, ADR-0199, ADR-0203, ADR-0204, ADR-0208, ADR-0210, ADR-0221, ADR-0222, ADR-0223, ADR-0226, ADR-0227, ADR-0228, ADR-0230, ADR-0231, ADR-0232, ADR-0233, ADR-0235, ADR-0236, ADR-0238, ADR-0240, ADR-0241, ADR-0242, ADR-0245, ADR-0246, ADR-0247, ADR-0260, ADR-0274, ADR-0286, ADR-0293, ADR-0295, ADR-0297 and ADR-0300.

## Context

**What obliges it.** ADR-0309 supersedes the decisions the owner named and the five checked
against the old answering prompt's supply. Its §5:1 lets a deletion lane remove code only
the old path uses that its list does not name, but a deletion lane writes no ADR record. Each
decision ADR-0309 supersedes keeps binding the old path's code until the lane that removes it
merges (ADR-0309 §1:3); the decisions it does not name were left binding with no end. #2836
asks for one sweep, once the deletions have run, so that no ratified decision stands over
code that no longer exists.

**What the cutover deleted, at `5bffba96`.** The whole of `context/`; `models/streaming.py`;
`permissions/routing.py`; `planning/associator.py` and `planning/composer.py`; and in
`orchestration/` the turn loop (`loop.py`), the composing stage (`composing.py`), the step
runner and executor (`runner.py`, `executor.py`, `effects.py`), the read-round servicer
(`reads.py`), the turn's retrieval (`retrieval.py`), `origin.py`, `evidence.py`, routing,
reconciling, the startup recovery scan (`recovery.py`), the goal and interpretation stages,
the question stage (`questions.py`), the old goal-authorization module and its surface,
quotes, stated bounds, charges, validating, verification, the capability alias layer, the
event-summary stage and the interim tidy-up. `AssistantEngine` lost `converse`, `resume`,
`pending_confirmations`, `cancel_read`, `converse_spoken`, `goals`,
`withdraw_clarification`, `abandon_goal`, `standing_authorizations`,
`revoke_authorization`, `answer`, `questions`, `interrupted_questions`, `forget_question`,
`grantable_decisions` and `establish_recipient_grant`, with their commands and panels.

**What is being deleted.** Lanes in flight delete the old planner (`planning/planner.py`),
the parked-reads store (`permissions/parked_reads.py`), the deferred-question store
(`memory/deferral_store.py`) and the goal authorizations
(`permissions/goal_authorizations.py`); `planning/goals.py` retires under ADR-0309 §5:1. The
owner ruled on 2026-10-14 (#2816) that the old planner, the query composer and the streaming
completer retire with their seams, and that `context/` is deleted and `learning/` kept.

**The sweep.** Every ADR numbered below 0306 whose status is not already wholly superseded
was read against `5bffba96`, clause by clause where it is marked, section by section where
it is not. A clause retires here when the code it obligates, constrains or describes is in
the lists above. A clause about a type, store member or seam that survives in `core` or in
its subsystem stands, even where nothing in production calls it now; those are listed under
"What stays open". The decisions ADR-0309, ADR-0313 and the old path's wire vocabulary
decision (ADR-0318) record are not recorded again.

**Four decisions the deletions leave.**
- *The startup stamp.* ADR-0119 §9:4 has the configuration trace record, for every control
  that can drive a traced read past §3's cap, the effective `search` limit it produces. The
  key that carried it, `retrieval_search_limit`, recorded `RETRIEVAL_LIMIT`, the old
  learning loop's retrieval limit; nothing in production searches with it now. Recall asks
  `search` for `RECALL_ITEM_LIMIT` plus the records it may pass over (ADR-0282 §4:2), so its
  limit depends on each activation's windows, and an event's supplied history is not capped.
  The dispatcher ruled on #2989 that the key retires, since no startup figure can say
  whether recall could truncate.
- *An `ASK_USER` memory ruling.* ADR-0078 queued one as a durable question, and ADR-0309
  supersedes it whole. Once the store is deleted, the orchestration write stage
  (`MemoryWriteStage`), whose one caller is consolidation (off by default, ADR-0309 §6:6),
  has nowhere to put the question. The remember capability and the authorizing phase already
  read such a ruling as not done and as needing the user, under ADR-0306.
- *`UserConfirmation`.* ADR-0078 §3 named the answer path the sole producer of a
  `UserConfirmation`, and that path retired with `orchestration/questions.py`. No production
  module constructs one, while `memory/policy.py` and `memory/ingest.py` still honour one
  (ADR-0106 §6:1–§6:3, ADR-0214 §3:2). `tests/orchestration/test_confirmation_authority.py`
  pins that none is constructed.
- *ADR-0185 §11's arms.* §11:3 drives "all three uses and both readers". The `FACET` driver
  went with `context/` and the `INGEST` driver with ADR-0294, so the one driver left is the
  upcoming-event producer's `NOTIFY` read (`UpcomingEventStage`), which reads the calendar;
  the email reader has no driver. The arms' test already runs over that driver alone
  (`_DRIVEN` in `tests/world/test_m24_read_trail_arms.py`).

## Decision

We will supersede the decisions whose every clause governed code the cutover deleted, and
the clauses of others that did; keep every clause that governs surviving code; narrow
ADR-0119 §9:4 and ADR-0185 §11:3 to what survives; log an `ASK_USER` ruling that has no
queue; and leave every producer of `UserConfirmation` to the authority milestone.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the dispatcher's authorization to ratify stands.

> **Normative.** The lanes that implement §4 and §5, the stamp lane of #2989 and the
> deferred-question store's deletion lane, merge only after this decision has merged
> `Accepted`.

> **Normative.** Each clause this decision retires keeps binding the code it governs until
> the lane that removes that code merges, and no lane builds on it meanwhile.

### 2. What retires whole

> **Normative.** The decisions §8's first table names are superseded whole: every clause of
> each still in force governed only code the cutover's lanes deleted or are deleting.

### 3. What retires in part

> **Normative.** Of each decision §8's second table names, the clauses that table names are
> superseded, and every other clause of that decision stands.

> **Normative.** Where a clause that stands names a deleted module, stage, engine member or
> implementation as one of several things it governs, that limb binds nothing and the rest
> of the clause binds as written. No record is written for such a limb.

> **Normative.** A clause this decision does not name stands as written. A lane that finds
> another decision standing only over deleted code files an issue, and a later ADR records
> it.

> **Normative.** Where a retired clause's subject is authority (asking the user before a
> call, a confirmation and its token, a parked read, the establishing act), it retires
> because its code is gone, and the owner's authority milestone redoes the subject. Nothing
> here decides how.

### 4. The startup stamp

> **Normative.** ADR-0119 §9:4 does not reach a control whose effective `search` limit
> depends on each activation's data, as recall's does under ADR-0282 §4:2. The allowlist
> records no figure for such a control.

> **Normative.** The configuration trace's `retrieval_search_limit` key retires, with
> `Composition.retrieval_search_limit`, `RETRIEVAL_LIMIT` and `EPISODIC_SUPPLEMENT_LIMIT`,
> in the lane #2989 names.

> **Normative.** Exclusion from an identity-based measure stays per trace, on ADR-0119 §3's
> truncation declaration as §9:5 has it, and that covers recall whatever its limit.

> **Normative.** The `conflict_search_limit` key stays: the ingestor's conflict search has a
> fixed limit, and §9:4 still reaches it.

### 5. An `ASK_USER` ruling with no queue

> **Normative.** Once the deferred-question store is deleted, an `ASK_USER` ruling the
> orchestration write stage receives writes nothing and queues nothing, and the stage logs
> it with the ruling's kind and the proposal's memory kind alone. The log carries no
> identifier and no content of the proposal, since a memory id is not guaranteed free of
> personal data (ADR-0004 §5).

> **Normative.** Consolidation counts such a ruling as deferred and records its chunk as
> done. Nothing is re-proposed for it.

> **Normative.** This holds until the owner's learning milestone decides what an `ASK_USER`
> ruling becomes, and no lane builds a store, a queue or a surface for one before then.

### 6. `UserConfirmation`

> **Normative.** No lane adds a production module that constructs a `UserConfirmation`. A
> producer is an authority change, and the owner's authority milestone decides it.

> **Normative.** `memory/policy.py` and `memory/ingest.py` keep honouring a
> `UserConfirmation` as ADR-0106 §6:1–§6:3 and ADR-0214 §3:2 decide, and the structural
> test keeps pinning that no production module constructs one.

### 7. ADR-0185 §11's arms

> **Normative.** ADR-0185 §11's arms run over the read drivers that survive, which are the
> upcoming-event producer's `NOTIFY` reads and the reader they drive. §11:3's "all three
> uses and both readers" reads as every use and every reader a surviving driver reaches.

> **Normative.** A lane that adds a driver of a source read adds its use and its reader to
> the arms in the same change.

### 8. Relationship to earlier decisions

Superseded whole (§2):

| Earlier decision | What it governed |
| --- | --- |
| ADR-0022 | `LearningLoop` in `orchestration/loop.py`: its `respond`, its stage order, its failure table, its write path and its tuning check |
| ADR-0033 | `AssemblingContextProvider`'s drain after a required source fails, in `context/provider.py` |
| ADR-0034 | What `StepExecutor` in `orchestration/executor.py` may do between the claim and the call |
| ADR-0047 | `ModelBackedPlanner`'s prompt, envelope and extraction in `planning/planner.py`, and the `Planner` seam it implements |
| ADR-0051 | `StepExecutor`'s revalidation of the result the seam returns, in `orchestration/executor.py` |
| ADR-0053 | The selection-time capability alias layer, `orchestration/capability_alias.py` |
| ADR-0055 | `ContextSource.name` and the assembler that logged it, in `context/` |
| ADR-0057 | `AssemblingContextProvider.assemble`'s observation of its sources, in `context/provider.py` |
| ADR-0058 | `StepExecutor`'s construction without an `AuditTrail`, in `orchestration/executor.py` |
| ADR-0071 | The planner's envelope scan, `_extract_object` in `planning/planner.py` |
| ADR-0158 | §2:2, the one clause ADR-0309 left: the callers of `assemble_by_band` in `orchestration/retrieval.py` |
| ADR-0160 | The episodic supplement's bound, in `orchestration/retrieval.py` and `orchestration/loop.py` |
| ADR-0170 | What ADR-0307 left to the old path: the composing stage in `orchestration/composing.py` and the reply `converse` and `resume` returned |
| ADR-0176 | The planner's decline in `planning/planner.py` and the turn loop's empty-plan branch in `orchestration/loop.py` |
| ADR-0201 | The routed `forget`'s lookup in `orchestration/routing.py`; ADR-0004 §6 and ADR-0074 §8 keep binding what `forget` destroys |
| ADR-0211 | The planner's capability roster: `Planner.plan`'s `capabilities`, the turn loop's read of it, the planner's prompt and envelope, the composing stage's rendering and the alias layer |
| ADR-0244 | The parked read: `permissions/parked_reads.py`, `orchestration/parked_reads.py`, `resume` and `pending_confirmations`; the authority milestone redoes asking before a call |

Superseded in part (§3); every clause the middle column does not name stands:

| Earlier decision | What retires | What it governed |
| --- | --- | --- |
| ADR-0008 | §2's `ContextSource` seam, §3, §4's bullets on a failing optional source and a key collision, and §5's working-hours window and source clock, with ADR-0026's amendments to them | The assembler and its sources in `context/`, and the two `Settings` fields that went with them |
| ADR-0014 | §1's `Goal`, §5's goal members and goal deletion, §4's startup recovery scan, §6's `Planner` Protocol and §7's model-backed planner | `planning/goals.py`, `PlanStore`'s goal members, `orchestration/recovery.py` and `planning/planner.py` with the `Planner` seam |
| ADR-0028 | §4's ruling on `LearningLoop`, with its `LearningLoop` limbs in §4a and §4b | `LearningLoop` in `orchestration/loop.py`; the writer itself, its tuning check and its expiry clock stand |
| ADR-0029 | §8 but its two wiring bullets, and §4's paragraphs obliging the executor on a cancelled call | `StepExecutor` in `orchestration/executor.py`; the seam's own rules stand |
| ADR-0037 | §1's disposition table, §4, §5 and §6 | `StepRunner` in `orchestration/runner.py`: its dispositions, its park, its one-commit denial and its entry state; §2–§3's decide, record and read back stand, as the authorizing phase relies on them |
| ADR-0039 | §6, and §7's bullet on cross-restart retry | What `StepExecutor` in `orchestration/executor.py` wrote and retried; `StepFailure` and its rules stand |
| ADR-0042 | §3's `converse` and `resume` call shapes, and §4 | `converse`, `resume` and the confirmation token, which left the engine surface; the authority milestone redoes asking the user |
| ADR-0049 | §1's `goals` table and its goal-side rules, and §4 | `PlanStore`'s goal members and the parked `CONFIRM` path in `orchestration/runner.py` |
| ADR-0052 | §1–§3, and §4's command-line `resume` bullet | `pending_confirmations`, `resume` and `assistant resume`, which are gone; the authority milestone redoes asking the user |
| ADR-0059 | §1's computing of `expires_at` and its freshness check in the step runner, and §3 | `StepRunner` in `orchestration/runner.py`; the field and `AuditTrail.resolution_of` stand, and the authority milestone redoes asking the user |
| ADR-0060 | §3's `ContextProvider` leg | `AssemblingContextProvider` in `context/provider.py` |
| ADR-0074 | §5, and §6's first paragraph | The conversation's tail and retrieved beliefs as `Planner.plan`'s supply, in `planning/planner.py` and `orchestration/retrieval.py` |
| ADR-0083 | §1's startup recovery scan, §2's `max_outstanding_confirmations`, §7's `DeferralStore.purge` limb and its bullet on confirmation deadlines, §13's #333 bullet and §14's item 7 | `orchestration/recovery.py`, the parked confirmation, `memory/deferral_store.py` and the continuation token |
| ADR-0084 | §7, and §8's ruling that `StepOutcome` names the driven step | `resume`'s continuation token and the driven step's outcome, which left the engine surface |
| ADR-0085 | The members `resume`, `pending_confirmations`, `questions`, `interrupted_questions` and `forget_question` wherever §3, §3a, §3b, §9 and §10 decide them; §7; and §4's and §5's rows for the types only those members reached | The five members, which left `AssistantEngine` (ADR-0309 §5:1) |
| ADR-0093 | §3:3, §3:4, §6:2 and §7a:2 | The facet path through `context/` |
| ADR-0096 | §3:3, §3:4, §5:5 and §5:6 | The context assembly and its reader adapter in `context/` |
| ADR-0097 | §5a:7 | A facet left out of `CurrentContext` for want of a `FACET` grant, in `context/` |
| ADR-0106 | §6:9 and §10:9–§10:11 | The deferred-question queue in `memory/deferral_store.py` and the answer path |
| ADR-0115 | §5:2–§5:4, §7:4 and §7:7 | Queuing an `ASK_USER` ruling from a reading, into `memory/deferral_store.py` |
| ADR-0119 | §9:4, for a control whose effective `search` limit depends on each activation's data | The startup stamp's `retrieval_search_limit` key, which no startup figure can fill for recall (ADR-0319 §4) |
| ADR-0122 | §3:1–§3:3, §4:1, §5:1 and §7:2 | The learning loop's resolution of a correction's kind, in `orchestration/loop.py` |
| ADR-0144 | §5:3, §5:4 and §6 | `StepRunner.resume` and the ambiguous-capability disposition in `orchestration/runner.py`; selection's order stands |
| ADR-0148 | §8:4, and §9:1–§9:4 as ADR-0306 left them | The egress `CONFIRM`'s content and the claimed plan step, in `orchestration/runner.py`; the authority milestone redoes asking the user |
| ADR-0150 | §10:3 and §12:16 | The egress `CONFIRM` the step runner raised; the binding stands |
| ADR-0162 | §9 | The answering supply's two limits, held equal to `orchestration/loop.py`'s |
| ADR-0173 | §3, §4:1–§4:2, §4:4, §4:6, §5–§9, §10:3, §14:1–§14:4, §14:6–§14:7, §14:9–§14:11 and §14:13 | `converse_streaming`, the `StreamingCompleter` seam with `models/streaming.py`, and the composing stage's stream; the chunk frame and `ReplyChunk`'s shape stand (ADR-0296 §4:3) |
| ADR-0175 | §3:1–§3:4 | The browser's streamed and whole turn, which no gateway route serves |
| ADR-0177 | §5:5, §8:3–§8:8 and §9:1–§9:2 | The browser's `forget_question` ceremony, its answer to a confirmation, and `resume`'s budget; the authority milestone redoes asking the user |
| ADR-0178 | §5:1–§5:4 and §9:4–§9:5 | The engine's two confirmation assembly sites and the parked step |
| ADR-0181 | §3:3, §5:5 and §5:6 | The confirmation assembly sites and the resuming path |
| ADR-0185 | §11:3, in its "all three uses and both readers" | The `FACET` driver in `context/sources.py`; the arms run over the surviving driver (ADR-0319 §7) |
| ADR-0187 | §3:1, §4, §4d, §5, §6:1 and §7:1 | The retrieval assembler's band floor in `orchestration/retrieval.py` |
| ADR-0189 | §2:2–§2:4, §3:1–§3:2, §4:4–§4:6, §9:5, §9:7 and §9:9 | The `Question`, `Retirement` and `Warrant` projections and their renderers |
| ADR-0192 | §3:36–§3:52 | The startup recovery scan in `orchestration/recovery.py` |
| ADR-0193 | §2:5, §2:6, §2:8, §2:9 and §2:13–§2:15 | The establishing act's surface, refusal and ordering, which left the engine surface; the authority milestone redoes the act |
| ADR-0199 | §5:2 | The old turn's `TurnResult` and composing stage |
| ADR-0203 | §1:3, §2:4, §3:1–§3:6, §4:1, §5:2, §6 and §7 | The old turn on an operation of unbounded audience: its `TurnResult`, plan, step and capture |
| ADR-0204 | §2:1, §2:4 and §2:5, as ADR-0309 left them | The old turn's evaluation site, a parked turn's capture, a routed pass and a resumption |
| ADR-0208 | §1:3–§1:5, §2:2–§2:3, §3, §4:1 and §6:2–§6:4 | The turn path's supply, the alias rows and the planner's decline |
| ADR-0210 | §1:1–§1:2 as ADR-0309 left them, and §9 | The turn's relevance reads and the tests over the spoken operation and the composing stage |
| ADR-0221 | §1:2, §1:3 and §5:6–§5:8 | The composing stage's no-reply shapes, a stream's stop, and the spoken, parked, recovered and routed captures |
| ADR-0222 | §4, §5, §6 and §8 | The reply's rendering in `planning/planner.py` and `orchestration/composing.py` |
| ADR-0223 | §1:1, §2:1, §3:3, §3:4 and §4 | The old turn's capture of its supply's externality |
| ADR-0226 | Every clause but §4 | The planner's read request and the turn loop's servicing in `orchestration/reads.py` |
| ADR-0227 | Every clause but §7:1 and §7:3 | The citation hop's reply rendering through `orchestration/reads.py` and the composing stage |
| ADR-0228 | Every clause but §5:1, §5:5, §5:6, §5:12, §6:1–§6:3, §12:4 and §12:7 | The revised plan and the turn's read loop |
| ADR-0230 | §2:1–§2:6, §3, §7, §8:1, §8:2, §8:6, §9, §10:2–§10:4, §12:1 and §13:6–§13:8 | The planner's file ask and its servicing; the `Fetcher` seam stands |
| ADR-0231 | §2:1, §3, §4:1, §9:2–§9:3, §11, §12:1, §13:1–§13:6, §15:3, §16:2–§16:4, §17:1–§17:3 and §17:11–§17:12 | The planner's search ask, the `QueryComposer` with `planning/composer.py`, and the servicing in `orchestration/reads.py`; the `WebSearcher` seam stands |
| ADR-0232 | §7 | The turn's read audit in `orchestration/reads.py` |
| ADR-0233 | §11:2 and §14:8 | The confirmation surfaces and assembly sites, which are gone; the authority milestone redoes asking the user |
| ADR-0235 | §1, §2, §5, §6:7–§6:18, §8:2–§8:3, §9:2–§9:10 and §9:13 | The establishing act's operations, `resume`'s flag and the surfaces offering them; the authority milestone redoes the act |
| ADR-0236 | §5 | The read audit's cost ground in `orchestration/reads.py` |
| ADR-0238 | §2, §3:4, §5:2–§5:8, §5:10, §7:1–§7:2, §11, §12:1–§12:2, §12:4 and §13:5–§13:6 | The `SearchSupply` the `QueryComposer` was handed, and its servicing |
| ADR-0240 | Every clause but §2:1–§2:4, §2:6 and §11:3 | The planner's structured ask and its servicing |
| ADR-0241 | §3:1–§3:3, §3:5, §4:5, §6, §8 and §10 | The servicing site's deadline setting and dispositions |
| ADR-0242 | §1:8, §6–§10 and §11:1 | The composing stage's account of a search that did not happen, and its carrier |
| ADR-0245 | Every clause but §1:1 and §2:1 | The `SearchSupply` and its builder in `orchestration/reads.py` |
| ADR-0246 | Every clause but §1:4, §2:1, §2:5 and §4:4 | The `SearchSupply` and its builder in `orchestration/reads.py` |
| ADR-0247 | §1:5, §3:4, §3:6, §6:1–§6:8, §8:4 and §8:6 | The servicing site, the parked read and the read audit; the authority milestone redoes asking the user |
| ADR-0260 | §3:4, §11:4, §12:3 and §13:5 | The forecast read's namer and servicing; the `Forecaster` seam stands |
| ADR-0274 | §2:6, §3:5, §6:2, §6:8–§6:10, §8:2–§8:3 and §10:1 | The spoken and compatibility limbs of the conversational entry |
| ADR-0286 | §2:3 and §9:1 | `resume`'s admission write and its episode |
| ADR-0293 | §10:1–§10:3 | The adapter that wrote the compose stage's reply |
| ADR-0295 | §4:1 | The goal a stopped activation was working on |
| ADR-0297 | §2:2, §2:10, §4:6, §4:10, §4:12 and §4:14–§4:16 | The turn's drive, `resume`, the step runner and executor, the goal and the old adapter |
| ADR-0300 | §5:12 | The interim tidy-up, `orchestration/story_tidy_up_interim.py` |

| Earlier decision | What changes |
| --- | --- |
| ADR-0078, ADR-0197, ADR-0198, ADR-0224, ADR-0229, ADR-0248–ADR-0256, ADR-0258, ADR-0259, ADR-0261, ADR-0262, ADR-0264–ADR-0271 | Nothing: ADR-0309 superseded them |
| ADR-0021, ADR-0044, ADR-0133, ADR-0276, ADR-0283, ADR-0284, ADR-0294 | Nothing: the old path's wire vocabulary is ADR-0318's |
| ADR-0200, ADR-0205, ADR-0206, ADR-0207 | Nothing: ADR-0313 decided what of spoken conversation retires |
| ADR-0280, ADR-0281, ADR-0282, ADR-0292 | Nothing: ADR-0309 recorded what the cutover changes in them |
| ADR-0050, ADR-0079, ADR-0098, ADR-0159, ADR-0171, ADR-0214 | Nothing: the policy's `ASK_USER` ruling and its honouring of a confirmation are surviving code; §5 and §6 say what follows the store's deletion |
| ADR-0016, ADR-0041, ADR-0064, ADR-0145, ADR-0152, ADR-0184, ADR-0186, ADR-0194 | Nothing whole: what they bind survives in `core`, the stores or the tool seam; a limb naming the executor or `resume` binds nothing (§3:2) |
| ADR-0119 §9:5, ADR-0185 §1–§10 | Nothing: §4:3 and §7 rely on them |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of each ADR this section's first two tables name, atomically with this
> ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- No ratified decision is left binding a module, stage or engine member that no longer
  exists, so a reader of the corpus sees what binds the phases and nothing of the old path.
- The stamp lane and the deferred-question store's deletion lane have the record they need.

**What it costs.**
- The configuration trace no longer says whether recall's search could truncate; only each
  trace says whether it did.
- An `ASK_USER` ruling on a consolidation is dropped, logged, until learning decides
  otherwise. Consolidation is off by default.
- An open lane whose text cites a clause this decision retires is bound by it under
  ADR-0209 when this merges.

**What stays open.**
- Members and types that survive with no production caller since the cutover, so that the
  clauses binding them stand: `PlanStore`'s plan and execution members (`save_plan`,
  `get_plan`, `start_execution`, `commit_transition`, `active_executions`, `claim_effect`),
  with `ActionPlan`, `ExecutionState` and `PlanExecution`; `AuditTrail.pending_confirmation`,
  `resolution_of` and `open_invocations`; `ActionPolicy.resolve`; `EgressBinder.rebind`;
  `Confirmation` and its egress types; `RecipientGrant.established_from` and
  `PermissionDecision.from_confirmation`; the `ReadKind`, `ReadAsk` and `ReadRequest` family;
  `SearchDisposition`, `SearchNotServiced` and `ForecastNotRead`; `ReplyChunk`; and the
  `ContextProvider` seam with `CurrentContext`. Retiring them, and the clauses that bind them,
  is a later lane's and a later record's.
- What an `ASK_USER` ruling becomes (the learning milestone), and who may produce a
  `UserConfirmation` (the authority milestone).

## Alternatives considered

- **Leave the records to each deletion lane.** Not possible: an implementation lane writes no
  ADR record (ADR-0309 §5:1), which is why #2836 asks for one sweep.
- **Supersede only whole decisions.** Rejected: most decisions that governed the old path also
  govern something that survives, and a partial record is the only way to say which.
- **Retire the clauses of members with no production caller as well.** Not done: those
  members are still in `core` and in their stores, and no lane yet removes them; a record
  ahead of their removal would leave clauses retired over live code.
- **Keep the `retrieval_search_limit` key, recording the least recall reaches.** Rejected on
  #2989: a figure wrong near its own boundary is worse than none, and §9:5's per-trace
  exclusion already covers recall.
- **Keep an `ASK_USER` ruling's material and re-propose it on a later run.** Rejected: with no
  queue to hold the question, it would be asked of nobody on every run.
