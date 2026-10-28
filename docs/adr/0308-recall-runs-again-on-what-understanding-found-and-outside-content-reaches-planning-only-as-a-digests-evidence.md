# 308. Recall runs again on what understanding found, and outside content reaches planning only as a digest's evidence

- Status: Partially superseded by ADR-0312 (§5:6's placement, for the activation's own evidence shown to its own planning) and ADR-0314 (§6:4's *and go when the activation ends*, for the copy of a held result's text a digest's prompt carries into the diagnostic record, until the record's window deletes it) and ADR-0354 (§4:10's plain completion and §4:11's *a reply does not parse*, each in the addition alone: the digest's structured call) and ADR-0353 (§2:2's cues and §2:4's order within a band: each unclear point's gap, in place of each reference's phrase)
- Date: 2026-10-11
- Scope: the phases after understanding ([#2723](https://github.com/leonapivato/ai-assistant/pull/2723)), milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)), the third of their four decisions: recall's second run and what planning is shown of recall's finds, and digesting, which turns outside content into evidence. ADR-0306 decided capabilities, authorizing and acting, and ADR-0307 planning; the cutover decision is the fourth.
- Dependency: [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md) and [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md), both Accepted and merged at `1978419a`; recall (ADR-0281, ADR-0282, ADR-0300 §7), implemented at `5166d5bc`.
- Authorization: the owner accepted proposal #2723 on 2026-10-11 and, the same day, ruled this decision's content in a pass over it. The dispatcher assigned 0308. This ADR is the proposal's §1 and §6 converted under `docs/proposals/README.md` → "When it is decided". Those rulings authorize ratifying it once its reviews are green, for as long as it settles only what they leave open.
- **Changes `core`, so it is a contract-surface decision.** `RecallCue`, `ControllerStage` and `ControllerRule` gain members; `EpisodeProcessingRecord` gains the second run's record and the digests, appended as the episode is extended; `project_episode` renders evidence; three types are new. No Protocol changes. `EpisodeProcessingRecord` crosses the wire, so `PROTOCOL_VERSION` advances (§7).
- **Partially supersedes**, each for an activation the phases plan (§1:3), except where a scope below says otherwise:
  [ADR-0252](0252-evidence-is-what-a-response-supports-sufficiency-to-act-is-four-mechanical-tests-and-a-refresh-supersedes-the-row-it-displaces.md) (whole: evidence is a digest's list, with no sufficiency tests);
  [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) (§3:5's working set and §4:1–§4:2's enums, in the additions alone; §4:6's loop guard, for the recall stage alone);
  [ADR-0281](0281-recall-runs-before-understanding-and-understanding-reads-what-it-found.md) (§1:3's *before it is understood*, §3:1's one cue and §5:4's *understanding is due next*, each for the second run alone; §6:1's `RecallCue`, in the addition alone);
  [ADR-0282](0282-phases-read-and-write-the-working-episode-and-recall-searches-past-the-windows.md) (§2:2's *any stage may read it*, for the held results alone; §4:2's *at most `RECALL_ITEM_LIMIT` records in all*, for the second run alone; §4:3's *and nothing else*, in the addition alone);
  [ADR-0284](0284-an-episode-is-the-experience-of-processing-its-activation.md) (§8:1's projection, in the addition alone);
  [ADR-0286](0286-an-episode-is-open-while-its-activation-runs-and-frozen-when-it-ends.md) (§3:3's admitted differences, in the additions alone; §3:8's *no field is added for a stage's result*, for the second run and the digests alone).
- Partially superseded: 2026-10-11 by ADR-0312 — one scope. §5:6's placement, for the
  activation's own evidence shown to its own planning: its own digests' evidence is shown
  to its own planning on every pass. The placement governs every other reader,
  `project_episode`, the windows and recall included. Every other clause stands. This scoped
  replacement takes effect on ratification of ADR-0312. This reciprocal header record
  accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the
  ratified body below are preserved.
- Partially superseded: 2026-10-13 by ADR-0314 — one scope. §6:4's *and go when the
  activation ends*, for the copy of a held result's text that a digest's prompt carries
  into the diagnostic record where the owner has turned it on, until the record's window
  deletes it. The held results themselves still go when the activation ends and are never
  saved with the episode, and every other clause stands. This scoped replacement takes
  effect on ratification of ADR-0314. This reciprocal header record accompanies the
  numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body
  below are preserved.
- Partially superseded: 2026-10-27 by ADR-0354 — two scopes, each in the addition alone. §4:10's *a plain completion, `ModelProvider.complete`* and *its reply parsed as one JSON object*: or one structured call with the digest's shape and no `model` override, its value the parsed object (ADR-0354 §9:1). §4:11's *a reply does not parse*: a returned `invalid`, `empty` or `cut` (ADR-0354 §9:2). Every other clause stands. These scoped replacements take effect on ratification of ADR-0354. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-27 by ADR-0353 — §2:2's cues and §2:4's order within a band: the second run is cued by the latest understanding's `meaning` and the `gap` of each of its unclear points, in place of each reference's phrase, and within a band the meaning's records come first, then each gap's, in the order understanding recorded them (ADR-0353 §14:3, §14:4). Every other clause stands. This replacement takes effect on ratification of ADR-0353. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The proposal.** #2723 sets out how an activation goes from understood to done. ADR-0306
decided how a call's result is routed: record by record, by who wrote the text, with text
someone other than the user or the assistant wrote going to "a digest (the digesting
decision)" (ADR-0306 §5:14–§5:16). ADR-0307 decided that planning names results R1, R2…,
that its first round runs once "recall's second run, which the digesting decision decides,
has finished", and that a new round waits for every digest (ADR-0307 §5:1, §8:1, §8:6).
This decision is those two pieces.

**What is built, at `5166d5bc`.** Recall runs once, before understanding, with one cue: the
input's words (ADR-0281 §3:1). It keeps records past the windows (ADR-0282 §4), looks up the
stories of each episode it keeps (ADR-0300 §7), and records an `ActivationRecall` in the
episode, whose excerpt of an outside episode is never its raw input (ADR-0281 §6:3,
ADR-0284 §2:3). `RecallCue` has one member and was written to gain more. Every model-facing
rendering of an episode goes through `project_episode` (ADR-0284 §8). Evidence today is
ADR-0252's `GoalEvidence`, a goal-scoped row with four sufficiency tests for the goal model,
which the cutover decision retires. Outside content reaches a model as quoted source data in
one JSON object, attributed by its records (ADR-0098 §2, as the tidy-up does it, ADR-0303
§3:7); there is no shared helper.

**The owner's rulings, 2026-10-11.** Each clause below that records a ruling states it as
ruled. The clauses that settle what the rulings leave open are listed as such in the pull
request.

## Decision

We will run recall a second time, on what understanding found, for planning alone; show
planning an episode by its records and never by its raw outside input; and give every piece
of outside text planning would otherwise read to a digest, one tool-less model call that
answers one question with a list of marked evidence, which is all of it planning ever sees.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** No lane implements this decision until it has merged `Accepted` and the
> cutover decision has merged. Its lanes are cut then.

> **Normative.** Every earlier clause this decision replaces is replaced for an activation
> the phases plan and for no other, except where its header names a wider scope. The old
> turn loop keeps those clauses until the cutover decision removes it.

### 2. Recall's second run

> **Normative.** Recall runs a second time on a pass once understanding has recorded an
> understanding on it, and before planning's first round. The second run is the same
> recall stage, `RecallStage`, as the first.

> **Normative.** Its cues are the latest understanding's `meaning` and the `phrase` of each
> of its `references`, whether or not the reference resolved to a referent. Each distinct
> cue is searched on its own, with ADR-0281 §3:2's band searches.

> **Normative.** Each cue keeps records under the first run's threshold and per-cue limit
> (ADR-0281 §3:3, `RECALL_ITEM_LIMIT`), passing over what ADR-0282 §4:1 passes over and
> every record the first run kept, and each band search asks for the limit plus the
> number of records passed over, as ADR-0282 §4:2 asks.

> **Normative.** The run then keeps the cues' records up to a cap on the total,
> `RECALL_SECOND_RUN_CAP`, in ADR-0072 §5's band order: every cue's `ASSERTED` records
> first, then `ATTESTED`, then `DERIVED`, and within a band the meaning's records before
> each phrase's, in the order understanding recorded the phrases. A record more than one
> cue found is kept once, and its `found_by` names each kind of cue that found it.

> **Normative.** `RECALL_SECOND_RUN_CAP` is a composition-root constant whose value
> [#2589](https://github.com/leonapivato/ai-assistant/issues/2589) sets, and it is not above
> `RECALLED_ITEMS_MAX`.

> **Normative.** The audience rule applies as in the first run (ADR-0281 §4:1–§4:2): a
> record the predicate does not admit is simply absent, and on a pass of unbounded audience
> the searches ask for semantic records alone.

> **Normative.** The second run is failure-tolerant as the first is (ADR-0281 §5:1,
> §5:4), under a budget computed as recall's. A failed or timed-out second run is
> recorded, and planning goes on without it.

> **Normative.** Only planning is given the second run's finds. Understanding is never
> given them, and nothing recall finds makes understanding run again.

> **Normative.** `ControllerRule` gains `understood_not_recalled`, which answers when an
> understanding is recorded on the pass and there is no second-run decision, and makes
> `recall` due.

> **Normative.** The recall stage runs at most twice on a pass, the second time only under
> `understood_not_recalled`, and ADR-0280 §4:6's guard ends a pass that would run it a
> third time.

The kept records' provenance and stories are the first run's rules unchanged (ADR-0281 §4:4,
ADR-0300 §7). Where the rows sit in the table the controller is switched to is the cutover
decision's, as ADR-0307 §10:2 leaves planning's.

### 3. What planning is shown of what recall found

> **Normative.** An episode either run found is shown to planning by its records, through
> `project_episode` with `admit_outside_input` false (ADR-0284 §8:5): understanding's
> meaning, its rounds' messages and episode notes (ADR-0307 §10), and its evidence (§5).
> It is never shown by its raw outside input, and it is never digested.

> **Normative.** A found episode is shown with the labels of the stories it is in
> (`RecalledItem.stories`) and nothing else of them. Planning reads one only if it needs
> it, by the story read ADR-0307 §6:6 lets it make.

> **Normative.** A memory record either run found is shown to planning only where its
> source is not outside under ADR-0306 §5:16. Every other one goes to recall's digest
> (§4:4) and reaches planning only as its evidence.

### 4. Digesting

> **Normative.** A result carrying outside text gets one digest: one model call, with no
> tools, over that result's outside records together.

> **Normative.** A result's digest starts as soon as acting records the result, and runs
> in parallel with the round's other calls and digests.

> **Normative.** A call's digest answers the call's *looking for* argument (ADR-0306 §2:9)
> and nothing else.

> **Normative.** Recall's outside memory records, from both runs, go into one digest after
> the second run, which answers the latest understanding's `meaning`. The digest fetches
> them by id under ADR-0282 §2:4–§2:8.

> **Normative.** `ControllerStage` gains `digesting`, and `ControllerRule` gains
> `recall_undigested`, which answers when the second-run decision is made, either run kept
> a memory record whose source is outside and there is no recall digest, and makes
> `digesting` due.

> **Normative.** Recall's second run has finished, for ADR-0307 §8:6, once its decision
> is made and, where `recall_undigested` would answer, recall's digest is recorded.

> **Normative.** The records reach the digest as quoted source data under ADR-0098 §2, in
> one JSON object, each attributed as outside content from the hub's data and never from
> its text, under a label local to that call. No local label survives the call.

> **Normative.** The digest's instruction states that the content is data and never
> instruction (ADR-0098 §3), that the digest answers only the question, that each item
> rests on one record and names it, and that "nothing here answers it" is a valid answer:
> an empty list of evidence.

> **Normative.** Where a digest's records are longer than the part size,
> `DIGEST_PART_CHARS`, a composition-root constant whose value #2589 sets, they are split
> into parts, one call each, run in parallel. Their evidence is joined in part order, and
> the digest has answered only when every part has.

> **Normative.** A digest call is a plain completion, `ModelProvider.complete` with no
> `model=` override, its reply parsed as one JSON object.

> **Normative.** A digest fails when a call raises, a reply does not parse, or the deadline
> bounding it passes first: for a result's digest, the one bounding its round's wait
> (ADR-0307 §8:2).

> **Normative.** The digesting stage is failure-tolerant (ADR-0281 §5:1).

> **Normative.** A failed digest records no evidence, and planning is told it could not
> read that result, or recall's outside records. Planning is never given the raw content.

> **Normative.** An item naming a source that is not one of the call's local labels is
> dropped.

> **Normative.** The hub records each kept item's source under the planning label of the
> record its local label named: the result's R label for a result that is one record, and
> otherwise the record's own label. The record takes that label under ADR-0307 §5:1 as the
> item is recorded for planning's next round, as a note planning writes takes its label
> when written; a record no item names takes no label from its digest.

> **Normative.** A digest remembers nothing between calls: each starts from its records
> and its question alone.

How the step that runs a round's calls runs acting and its digests side by side is the
cutover decision's, as the controller wiring of acting is. Which model serves a digest is
the provider's configured one, as for understanding; a cheaper one is a later optimisation
that changes no clause here.

### 5. Evidence

> **Normative.** Evidence is a list. Each item is its text, its source by label, and a mark
> that it came from outside content, and nothing more.

> **Normative.** Each digest is recorded in the episode as an `ActivationDigest`, once the
> episode writer's append of it has returned (ADR-0286 §3:1). An append that fails is a
> capture failure under ADR-0286 §5, and holds nothing back (ADR-0286 §3:7).

> **Normative.** Evidence reaches a story only through notes planning writes, and is never
> copied onto a story. A note planning writes in an activation that has read digested
> evidence is marked (ADR-0303 §3:1, ADR-0306 §4:5).

> **Normative.** An activation has read digested evidence, for ADR-0306 §4:5, once its
> record carries a digest that answered, with or without items.

> **Normative.** Planning is shown evidence as outside content (ADR-0303 §3:7). Rendered
> for a later reader by `project_episode`, an episode's evidence shows each item's text and
> its mark, and not its source label, which names a thing only in the activation that
> recorded it.

> **Normative.** An episode's evidence is placed for the owner alone, as its episode notes
> are (ADR-0307 §4:4).

### 6. Held results and the follow-up

> **Normative.** Acting holds each result carrying outside text in its own part of the
> working episode (ADR-0282 §2:2), under the result's id, which acting mints when it
> records the result and which the result's R label names (ADR-0307 §5:1).

> **Normative.** For a result of the assistant's own records, such as a memory search,
> acting holds the ids of its outside records (ADR-0282 §2:3), and the digest fetches them
> by id under ADR-0282 §2:4–§2:8.

> **Normative.** Any other result is held as its text arrived.

> **Normative.** The held results are never saved with the episode (ADR-0282 §1:2), and go
> when the activation ends.

> **Normative.** Of the stages, digesting alone reads the held results, and planning never
> does (ADR-0307 §9:2).

> **Normative.** A follow-up is a call of one capability on the assistant's own records,
> whose one planner argument is a result's R label and whose *looking for* carries the new
> question. It declares the assistant's own records as its effect, as reading a story does
> (ADR-0306 §3:1); never leaves the hub; may carry outside text; never has an unknown
> outcome; and is safe to repeat. It runs directly against the held results (ADR-0306
> §3:3).

> **Normative.** A follow-up's result is the result it names, as held, under that
> result's label. It mints no result and holds nothing again, so ADR-0306 §5:14 sends it
> to a digest answering the new question. A follow-up naming a result with nothing held
> comes back not done, with the reason.

A memory record held by id is read at its current version, so one changed or forgotten
since is digested as it now stands, or not at all (ADR-0282 §2:6). Nothing saved holds a
held result, so neither consolidation nor an episode's projection can reach one. Recall's
outside records are asked about again by a memory search, which is itself a call.

### 7. The code it binds

| Code | Change |
| --- | --- |
| `RecallCue` | Gains `understood_meaning` and `understood_phrase` (ADR-0281 §6:1's *added to and never renamed*) |
| `EpisodeProcessingRecord` | Gains `recall_second_run: ActivationRecall \| None = None`, `None` on a record whose trigger is a `RecordedResumeTrigger` by validator, as `recall` is; and `digests: tuple[ActivationDigest, ...] = ()`. `schema_version` advances by one |
| `EvidenceItem` | New frozen record: `text`, `source` (a label) and `outside: Literal[True]`, the mark |
| `DigestOutcome` | New closed enumeration: `answered`, `failed` |
| `ActivationDigest` | New frozen record: `result`, the R label of the result digested or `None` for recall's digest; `question`; `outcome: DigestOutcome`; `evidence: tuple[EvidenceItem, ...]`, empty where `outcome` is `failed`; and `recorded_at` |
| `core: episode_extends` | Also admits `recall_second_run` taking its value once, and entries appended at the end of `digests` |
| `core: project_episode` | Also renders an episode's evidence, each item's text and mark, under the reader's audience (§5:5–§5:6) |
| `ControllerStage`, `ControllerRule` | Gain `digesting`; and `understood_not_recalled` and `recall_undigested` |
| `ActivationRecall`, `RecalledItem`, `RECALLED_ITEMS_MAX` | Unchanged; the second run records an `ActivationRecall` |
| `rests_on_recorded_external_content` | Unchanged; ADR-0306 §5:16 reads it |
| `ModelProvider`, `Message`, `ToolCallingCompleter` | Unchanged; a digest calls `ModelProvider.complete` |
| `RecallStage`, `Recalled`, `ActivationState` | Orchestration-local: the second run's cues, cap and passing over, and its decision held beside the first's |
| `RECALL_SECOND_RUN_CAP`, `DIGEST_PART_CHARS` | New composition-root constants; their values are #2589's |
| The held results | Acting's part of the working episode, never saved: ids for memory records, text as it arrived otherwise (§6) |

> **Normative.** The `core` types and functions the table names change, or are added, as
> it states.

> **Normative.** The change that adds `recall_second_run` and `digests` to
> `EpisodeProcessingRecord` advances `PROTOCOL_VERSION`, on ADR-0124 §9's rule, as does any
> change here to another shape the wire carries.

> **Normative.** No stored record written before these fields existed is read under this
> decision; the cutover decision's fresh data directory is what the phases start on.

### 8. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0072 §5 | Nothing: the second run fills its cap in band order across its cues (§2:4) |
| ADR-0098 §2, §3 | Nothing: the digest is the one model that reads outside text for planning, and reads it as quoted data |
| ADR-0106 §1 | Nothing: its predicate decides which memory records are outside (ADR-0306 §5:16) |
| ADR-0252 | Whole, for an activation the phases plan: evidence is §5's list, with no applicability, standing, verdict or sufficiency test |
| ADR-0280 §3:5, §4:1–§4:2 | The working set gains the second-run decision and recall's digest, and the enums the members §7 names, in the additions alone |
| ADR-0280 §4:6 | The loop guard, for the recall stage alone: it runs at most twice (§2:10) |
| ADR-0281 §1:3, §3:1, §5:4 | For the second run alone: it runs after understanding, searches with understanding's meaning and phrases, and is followed by planning rather than understanding |
| ADR-0281 §6:1 | `RecallCue` gains §7's two members, in the addition alone |
| ADR-0281 §6:3, §7:1 | Nothing: an outside episode's excerpt is still never its raw input, and understanding reads only the first run's records |
| ADR-0282 §2:2 | *Any stage may read it*, for the held results alone: digesting alone reads them (§6:5) |
| ADR-0282 §2:3–§2:8 | Nothing: held memory records, and recall's records for its digest, are ids fetched under them |
| ADR-0282 §4:2 | For the second run alone, `RECALL_ITEM_LIMIT` is per cue and the cap bounds the total (§2:3–§2:5) |
| ADR-0282 §4:3 | Recall's part of the working episode also holds the second run's `ActivationRecall` and scores, in the addition alone |
| ADR-0284 §8:1 | The projection also carries an episode's evidence, in the addition alone |
| ADR-0286 §3:3, §3:8 | §3:3's admitted differences gain `recall_second_run` taking its value and entries appended to `digests`, in the additions alone; §3:8's *no field is added*, for the second run and the digests alone |
| ADR-0306 §5:14–§5:16 | Nothing: §4 is the digest those clauses send outside text to |
| ADR-0307 §5:1 | Nothing: a digest's call uses local labels, and an evidence item's source takes its planning label as the item is recorded for planning (§4:15) |
| ADR-0307 §8:6 | Nothing: §4:6 says when the second run has finished |

> **Normative.** This numbered draft records its replacements on the status lines and in
> a dated header note of ADR-0252, ADR-0280, ADR-0281, ADR-0282, ADR-0284 and ADR-0286,
> atomically with this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies.
> The replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- A name the user used finds its memory, because understanding has placed it before recall
  searches the second time.
- Planning never reads outside text, so a page or an email cannot instruct it; it reads
  only what a digest says answers its question, marked as outside.
- An episode found later is read by what the assistant made of it, never by the text that
  came in from outside.

**What it costs.**
- Every result carrying outside text costs a model call, and a long one several.
- A round waits for the slowest call and its digest.
- A follow-up reaches only results of the same activation; a later one calls again.

**What stays open.**
- Recall running again on everything new, contesting a reference, and the hook that runs
  alongside the phases ([#2591](https://github.com/leonapivato/ai-assistant/issues/2591)).
- Memories cited by a story's earlier episodes
  ([#2528](https://github.com/leonapivato/ai-assistant/issues/2528)).
- The numbers: the second run's cap and the digest part size (#2589).
- Finer declarations, such as an invite's title shown marked instead of digested.

## Alternatives considered

- **A result's shape, structured or unstructured, deciding what is digested.** Replaced by
  who wrote the text (ADR-0306 §5:14).
- **Showing understanding the second run's finds.** Rejected: understanding would have to
  run again, once per recall.
- **Digesting a found episode.** Not needed: its records already say what the assistant
  made of it, and its raw outside input is never shown.
- **Building on ADR-0252's evidence record.** Rejected: its sufficiency tests serve the
  goal model, which retires.
- **A digest that remembers its earlier answers.** Rejected: a follow-up asks the stored
  result again with a new question.
- **Persisting held results for later activations.** Not done: an R label names a result
  only within its activation, so nothing later could name one, and a store of raw outside
  text would owe deletion, export and forgetting with no reader.
