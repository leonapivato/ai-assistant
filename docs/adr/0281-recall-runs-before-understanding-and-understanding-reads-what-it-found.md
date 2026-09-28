# 281. Recall runs before understanding, and understanding reads what it found

- Status: Proposed
- Date: 2026-09-27
- Scope: [M39](https://github.com/leonapivato/ai-assistant/milestone/6).
- Dependency: ADR-0280 and its milestone M38; ADR-0276 and ADR-0275.
- Authorization: the owner accepted the proposal on #2579 on 2026-09-27, after ruling its shape in conversation the same day, and directed its conversion into this ADR. The dispatcher assigned the next available number, 0281. That authorizes drafting and numbering, not ratification or implementation.
- **Partially supersedes** [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) — **three scopes.** **§4's `EpisodeProcessingRecord` field set, in the addition alone**: the record gains §6 below's `recall` field; every existing field, value and validator stands. **§7:4's rule that all automatic model-facing episodic reads request eligibility `True`, for one consumer**: recall's read (§3 below) requests no eligibility. **§9:6's exclusion of the trigger's raw input text from automatic model inputs, for one consumer and one field**: the trigger's exact input text or transcript of a recalled episode is admitted to the understanding stage's rendering of it (§7 below), as ADR-0276 admitted it to the episode window, and nothing else is.
- **Partially supersedes** [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) — **four scopes.** **§1:5**, in its *no retrieved memory* and *nothing else* parts alone: the stage also reads what recall found. **§2:5's referent kinds, in the addition alone**: `UnderstandingReferent.kind` gains `memory`. **§3:3's label scheme, in the addition alone**: a third sequence, `M`. **§5:1's *before any relevance read***, for recall's read alone. Every other clause stands.
- **Partially supersedes** [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) — **four scopes.** **§3:5's working set and §4:1–§4:3's enums and table, in the additions alone**: the recall decision, the stage `recall`, the rule `not_recalled` and its row. **§5:2's fixed default, for a failure-tolerant stage alone** (§5 below). **§7:1's `schema_version` literal alone**: it becomes `Literal[4]`. Every other clause stands.
- **Partially supersedes** [ADR-0217](0217-a-record-carries-who-may-receive-it-and-a-model-may-only-narrow-it.md) — **one scope.** §2:5's *no new site* half, for one further site: the same record-level predicate applied to recall's records (§4 below). Every other clause stands.

## Context

An activation is understood today from its input and two windows of short-term
memory: the recent items on its channel and the assistant's recent episodes
across channels (ADR-0276). The understanding stage reads no long-term memory
(ADR-0276 §1:5). The turn loop does read long-term memory, twice, before
planning (`LoopEngine`'s belief composition and episodic supplement), but those
reads are keyed on the goal's statement, run after understanding, and feed
planning, not understanding.

The owner's direction on the wiki's
[Recall](https://github.com/leonapivato/ai-assistant/wiki/Recall) and
[Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller)
pages (revision `f18ccf6`, direction and not ratified) adds a model-free
**recall** phase that runs first, gathers what might bear on the activation,
and adds it to the episode for understanding to use. ADR-0280 built the
controller that phase plugs into.

The owner ruled M39's shape on 2026-09-27:

- shape first, and a simple search, not much new;
- episodic and semantic memory only, since preferences are not populated yet
  and procedural memory waits for the phases after understanding;
- no recall hook;
- no design of forgetting copies already recalled into episodes, which comes
  when routing and the memory commands return;
- basic audience and provenance, with getting them right left to a later
  milestone;
- breakage elsewhere allowed if each break is listed.

In reviewing the proposal, the owner also ruled:

- **Recall belongs to the activation, not to a conversation.** Every activation
  gets it the same way, whatever channel it came on.
- **Recall is thin.** Before understanding the only cue is the activation's raw
  words. That is a good cue for an input with content in it, and a poor one for
  "yes" or "same as before", where a similarity search returns noise that looks
  relevant. So the first recall adds a few strong matches and leaves the work of
  connecting an activation to what came before to short-term memory, to recall
  cued by understanding (the hook, later), and to candidate stories (later).
- **Recall later suggests candidate stories and never chooses one.**
- **`model_eligible` is a compatibility flag, not an audience filter.** It
  exists so the model reads from before M36 keep seeing what they saw (ADR-0276
  §4's own reading). It marks newly captured events, pre-result failures and
  interruptions as ineligible, and the data directory is fresh since M37.

`MemoryStore.search` (ADR-0237) already costs one embedding and a `sqlite-vec`
lookup and no model call. Its scores are cosine similarities, so their scale
belongs to the embedder: `FastEmbedEmbedder` and `HashingEmbedder` put the same
pair of texts at different scores.

## Decision

### 1. Status and scope

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one
> tree and the owner's authorization to ratify stands; an assigned number or a
> green review alone does not change its status.

> **Normative.** No implementation, canonical fake included, implements this
> decision until this numbered ADR has merged `Accepted` under ADR-0015 §5.

> **Normative.** **Recall** is the stage that searches long-term memory for an
> activation before it is understood and records what it found. It runs on
> every activation ADR-0280's controller runs, and reads nothing about the
> activation's channel type, payload modality, operation or audience in
> deciding whether it runs. It does exactly the wiki's recall phase's job and
> nothing else, so under ADR-0280 §1:3 it takes that phase's name.

**Why a stage and not part of understanding.** Inside the understanding stage,
the stage record could not tell a recall that failed from an understanding that
failed, and the recall hook will need recall to be something the controller can
run again.

### 2. The stage and its rule

> **Normative.** `RecallStage` is an orchestration-local class in
> `orchestration/recall.py`, holding an injected `MemoryStore`, and calls no
> model. It is not a Protocol, and `core/protocols.py` gains no member for it.

> **Normative.** `ControllerStage` gains the member `recall` and
> `ControllerRule` the member `not_recalled`, on ADR-0280 §4:1–§4:2's *added to
> and never renamed* rule. ADR-0280 §3:5's working set gains the **recall
> decision**: the outcome of §6's result, present once the stage has made it,
> `nothing_found` and `failed` included.

> **Normative.** ADR-0280 §4:3's table gains one row between `route_taken` and
> `not_understood`: `not_recalled` answers when *the recall stage and the
> understanding stage are both wired and there is no recall decision*, and makes
> `recall` due. No other row's order changes; the rows after it are renumbered
> by one.

Rows 1–3 answer only for conversation turns and are quarantined for removal
(ADR-0280 §2), so on every activation recall is the first stage to read the
input. Recall without understanding has no reader, which is why the rule needs
both stages wired.

### 3. What it searches

> **Normative.** Recall searches with **one cue**, the activation's input text
> exactly as the pass holds it, and with nothing else: not the channel window,
> not the episode window, not a goal.

> **Normative.** Recall reads **per band**, on ADR-0072 §5's consumer-side
> precedence: one `MemoryStore.search` for each of `ASSERTED`, `ATTESTED` and
> `DERIVED`, in that order, each with the cue as its query, `bands` that one
> band, `kinds` episodic and semantic (or semantic alone under §4:2),
> `limit` `RECALL_ITEM_LIMIT`, no other filter and **no eligibility**
> (`episode_model_eligible` unset).

> **Normative.** Recall fills `RECALL_ITEM_LIMIT` in band order: from each
> band's results, in the store's order, it keeps a record only when its `score`
> is at or above the **recall threshold** and it passes §4's audience
> predicate, and it stops once the limit is filled. A record returned with no
> `score` is not kept. `capped` is not acted on, as the loop's own reads leave
> it.

> **Normative.** The recall threshold is a constructor argument of
> `RecallStage`, not a constant: the composition root sets it for the embedder
> it wires, beside that embedder, because a score's scale belongs to its
> embedder. The value for `FastEmbedEmbedder` is chosen so that a short input
> carrying no content, such as "yes", "ok" or "same as before", normally keeps
> nothing, while a paraphrase of a stored fact keeps it. The implementation PR
> records the measurement it chose the value from. Tests set their own
> threshold for the embedder or fake they use.

> **Normative.** `RECALL_ITEM_LIMIT` is a composition-root constant beside
> `UNDERSTANDING_EPISODE_LIMIT`, with initial value **3**.
> `ai_assistant.core.config.Settings` gains no field for it or for the
> threshold.

> **Normative.** Recall interprets nothing. It does not decide that a memory
> answers anything, is out of date, is relevant or settles a reference, and it
> resolves no reference.

**Why one cue, the words alone.** Understanding already reads the channel
window as short-term memory, so searching with it too mostly repeats that
context and adds loosely related items. What connects a short input to the
past is structure, the story it continues, not similarity.

**Why per band.** With a limit of three, one band-neutral search would let
three inferences that score higher displace an assertion below the cut, where
no later ordering recovers it. ADR-0072 §5 rules that out for every consumer
assembling context. Three band-scoped searches still cost milliseconds and no
model call.

**Why no eligibility.** Requesting eligibility `True` would hide every episode
captured from a channel other than the conversation, as well as failures and
interruptions. Recall is meant to reach those.

### 4. Basic audience and provenance

> **Normative.** Recall applies `admitted_to_understanding`, the predicate the
> understanding stage's two windows already use (ADR-0276 §4), to the records
> searches returned, before any is kept. No controller rule reads the
> audience.

> **Normative — a turn on a channel of unbounded audience recalls no episode.**
> On the operation ADR-0250 §15 names (`converse_spoken`, as ADR-0200 §3
> declares it), recall's searches ask for semantic records alone, so no episode,
> and no earlier understanding, reaches the turn through recall. This is
> ADR-0276 §4:13's rule read over the one new carrier this decision adds; the
> stage applies it from the pass's audience posture, as the understanding stage
> applies §4:13, and no controller rule reads it.

> **Normative.** Each kept record carries one of two provenance values:
> **`outside`**, for a semantic record `rests_on_recorded_external_content`
> places there, or for an episode whose trigger arrived on the informational
> event channel; and **`user`**, for every other record. Nothing finer (band,
> attestation source, the connection) is recorded by this decision.

On a bounded-audience channel the predicate withholds nothing. On the spoken
operation's unbounded audience, which ADR-0280 §2 keeps, recall reaches no
episode at all, and the predicate withholds silently every semantic record it
does not place, as it does for the windows. The audience milestone changes
these rules, not the stage's shape.

### 5. Failure, and the two deadlines

> **Normative.** A stage may be declared **failure-tolerant**. A
> failure-tolerant stage catches the failures it handles, records its decision
> in the working set before it returns, and returns a `StageResult` of `failed`
> or `timed_out` carrying the error instead of raising it.

> **Normative.** For a `failed` or `timed_out` result returned by a
> failure-tolerant stage, while the pass's deadline has not passed, the
> controller appends the stage's entry with that outcome and continues
> evaluating the rules, instead of applying ADR-0280 §5:2's fixed default.

> **Normative.** ADR-0280 §5:2's fixed default still applies to a
> failure-tolerant stage when an error escapes it (a raise, which is `failed`
> under ADR-0280 §5:1) and whenever the pass's deadline has passed, whatever
> the stage returned: the pass ends with `stage_failed` or `stage_timed_out`
> and the error is re-raised.

> **Normative.** `RecallStage` is failure-tolerant. It runs its search under
> **recall's budget**: the smaller of `RECALL_BUDGET`, a composition-root
> constant with initial value **2 seconds**, and the time left before the
> pass's deadline. When the search raises `MemoryStoreError`, recall records
> `failed` and returns `failed`. When recall's budget runs out, recall records
> `timed_out` and returns `timed_out`. In both cases understanding is due next.

| What ran out or failed | Recall records | The pass |
| --- | --- | --- |
| The store raised `MemoryStoreError` | `failed` | continues to understanding |
| Recall's own budget | `timed_out` | continues to understanding |
| The activation's deadline | nothing further | ends: `stage_timed_out`, re-raised |
| Any other error escaping the stage | nothing further | ends: `stage_failed`, re-raised |

**Why an amendment and not a caught error returning `done`.** Returning `done`
from a recall that failed needs no amendment, but the stage record would then
say `done` for a recall that failed, and only the recall field would be right.
ADR-0280's record exists to say what happened. Because a tolerant stage records
its decision before it returns, the rule that made it due does not answer
again. If a stage broke that obligation, ADR-0280 §4:6's loop guard would end
the pass with `stage_repeated` rather than loop.

### 6. What recall adds to the episode

> **Normative.** Add to `core/types.py` frozen, `extra="forbid"` models and
> closed enums, each enum **added to and never renamed**:
>
> - `RecallOutcome`: `found`, `nothing_found`, `failed`, `timed_out`;
> - `RecallCue`: `activation_input`;
> - `RecallProvenance`: `user`, `outside`;
> - `RecalledItem`: `kind: MemoryKind`, restricted by validator to `episodic`
>   and `semantic`; `id: EncodableText`, the record's stored `MemoryBase.id`
>   exactly as stored; `excerpt: EncodableText` of at most
>   `UNDERSTANDING_REFERENT_EXCERPT_CHARS`; `provenance: RecallProvenance`;
>   `standing: BeliefBand`, `band_of` the record's provenance source;
>   `rests_on_recorded_external_content: bool`, that function over the record's
>   provenance; `attestation: Attestation | None`, the record's
>   `Provenance.attestation` as stored, projected whole;
>   `found_by: tuple[RecallCue, ...]`, non-empty;
> - `ActivationRecall`: `outcome: RecallOutcome`; `cues: tuple[RecallCue, ...]`,
>   non-empty, the cues recall searched with; `items: tuple[RecalledItem, ...]`,
>   at most `RECALLED_ITEMS_MAX`, a `core` constant with value **16**, non-empty
>   exactly when `outcome` is `found`.

> **Normative.** `EpisodeProcessingRecord` gains `recall: ActivationRecall |
> None = None`. A pass on which recall made a decision carries it; a pass that
> ended before recall's decision carries `None`; a record whose trigger is a
> `RecordedResumeTrigger` carries `None`, enforced by validator.

> **Normative.** An item's excerpt is taken by `orchestration` from the record,
> never from model output, and cut to the bound:
>
> - a semantic record's `fact`;
> - for an episode whose trigger arrived on the informational event channel,
>   its latest understanding's `meaning`, or where it has none, the fixed text
>   that it was a report received on its channel;
> - for any other episode, its trigger's input text or transcript where the
>   trigger carries one, and otherwise its `content`. This covers an episode
>   with no processing record, one whose trigger is a `RecordedResumeTrigger`,
>   and one whose speech yielded no transcript. An empty `content` gives an
>   empty excerpt, which is a valid one.
>
> **An outside episode's raw input never enters the recall record.**

> **Normative.** The recall result is held on `ActivationState` once the stage
> ends, so understanding reads it in the same pass, and it is written **once**,
> at capture, into the processing record, on ADR-0280 §6:5's rule. The records
> the search returned are held on `ActivationState` for the pass for the
> understanding stage to render, and are never persisted.

> **Normative.** `EpisodeProcessingRecord.schema_version` becomes
> `Literal[4]`, and the episode-record format marker (`EPISODE_RECORD_FORMAT`)
> advances, on ADR-0275 §12's mechanism exactly as ADR-0280 §7:2 advanced it: a
> store written before this decision is refused before mutation with
> `IncompatibleStateError`. No migration, backfill or version-3 read path is a
> deliverable.

> **Normative.** The episode's canonical detail carries the recall result as it
> carries every other field, and the human rendering of `assistant episode`
> shows its outcome and each item's kind, provenance and excerpt. Each change
> that alters the processing record's shape advances `PROTOCOL_VERSION` in that
> change, on ADR-0280 §7:4's rule.

`RecalledItem` is shown to the owner in episode inspection, so it is a
user-facing projection under ADR-0189 §1: `standing`,
`rests_on_recorded_external_content` and `attestation` are its structured
origin, as the record holds them. `provenance` is the basic `user` or `outside`
label §4 derives, which is not the same fact: an informational event's episode
is `outside` while its `derived_from_external` is `False` (ADR-0275 §9:7).

`found_by` and `cues` have one member now. They exist so that later sources add
to the same record: recall cued by understanding, and candidate stories.

### 7. Understanding reads what was found

> **Normative.** The understanding stage receives the records recall kept, in
> recall's order, and the recall outcome. It still receives no goal, candidate
> goal, attempt, plan, context-provider state, or memory from any other read.

> **Normative.** A recalled record already rendered in the channel window or the
> episode window is rendered there only, under its `H` or `P` label, and is not
> rendered again. Every other recalled record is rendered in a third section of
> the prompt, `recalled`, under the label `M` followed by its 1-based index in
> that section in decimal with no padding, on ADR-0276 §3:3's scheme: no label
> survives the call and none is persisted as a reference.

> **Normative.** A recalled episode renders with ADR-0276 §4's projection, the
> projection the episode window uses, including its attribution as a report
> received and its provisional "understood then". A recalled semantic record
> renders its `fact`, its `provenance.last_updated` and one attribution by band:
> something the user said (`asserted`), something the assistant worked out
> (`derived`), or something a connected source reported (`attested`).

> **Normative.** The stage's instruction states that a recalled memory is what
> the assistant remembers: provisional, possibly out of date, and not relevant
> for being recalled. A reading supported by an `M` label is `supplied`, as for
> any label. When recall kept nothing, the section states that nothing was
> recalled; when it failed or timed out, the section states that recall failed.

> **Normative.** A cited `M` label for an episode resolves to the existing
> `episode` referent. A cited `M` label for a semantic record resolves to a new
> referent kind, `memory`: `id` the record's stored `MemoryBase.id` exactly as
> stored, `source` the text `semantic memory`, and `excerpt` on ADR-0276
> §2:5's rule.

`understanding_omitted` is unchanged: a recall that failed is not an omission of
understanding.

**Outside content as a cue.** An activation whose input is outside content,
such as an email, is still recall's cue. The wiki's two-readers rule holds:
recall calls no model, so nothing but understanding reads the outside content,
and understanding already may. Outside content does choose which memories
understanding is shown, which is acceptable because understanding only
describes and grants nothing.

### 8. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then the
> implementation ships as separate PRs in this order:
>
> 1. **`core` with `wire`, additive only**: §6's types, the `recall` field
>    defaulting to `None`, the referent kind `memory`, `schema_version` still
>    `Literal[3]` and no validator of §6, with a `PROTOCOL_VERSION` advance.
> 2. **`orchestration`, recall and understanding**: `RecallStage`, its
>    threshold and budget, and the understanding stage's rendering, labels and
>    resolution of §7, with recall wired into no controller yet.
> 3. **`orchestration`, the controller**: the stage, the rule and its row, the
>    failure-tolerant path of §5, and the result on `ActivationState` written at
>    capture. It lands after ADR-0280's step 2.
> 4. **The cutover, `core`, `memory` and `wire`, as one mechanical unit**:
>    `Literal[4]` with §6's validators, a second `PROTOCOL_VERSION` advance, and
>    the format marker's advance. It lands after ADR-0280's step 3.
> 5. **`interfaces`**: the rendering of §6.
>
> Step 2 depends on step 1, step 3 on step 2, and steps 4 and 5 on step 3.

> **Normative.** Step 3's tests assert, for each activation kind ADR-0280 §8:2
> names, the exact entries its record carries with the `recall` entry
> included, and over fake stages: a tolerated `failed` and a tolerated
> `timed_out` each followed by `understanding`; an error escaping a tolerant
> stage ending the pass with `stage_failed`; an expired pass deadline ending the
> pass with `stage_timed_out` from a tolerant stage; and no path reaching
> `stage_repeated`.

> **Normative.** Step 2's tests assert, against the canonical `MemoryStore`
> fake: the three band-scoped searches on the input, in precedence order; an
> assertion kept ahead of higher-scoring inferences; the threshold, the cap and
> a record with no score; the audience predicate; no episode searched for or kept on the
> unbounded-audience operation, including an episode the predicate would admit;
> each provenance value; that an outside episode's excerpt never carries its
> raw input; the excerpt of a resumed episode and of an episode whose speech
> yielded no transcript; and each `RecallOutcome`.
> Against the scripted model fake, they assert: `M` labels rendering; a
> recalled record already in a window not rendered twice; citations resolving
> to `episode` and to `memory`; and the nothing-recalled and recall-failed
> sections.

> **Normative.** Each implementation PR lists every existing behaviour it
> changes, each with its reason, and the gate passes on every PR.

### 9. Relationship to earlier decisions

> **Normative.** This numbered draft records its scoped replacements on each
> affected ADR's status line and in a dated header note, atomically with this
> file, under ADR-0070 §4 and ADR-0082 §1. Preserve earlier supersessions and
> every ratified body. The replacements take effect on ratification.

| Decision | Replaced scope and what remains |
| --- | --- |
| ADR-0275 §4 | The record gains `recall`. Every existing field, value and validator stands. |
| ADR-0275 §7:4 | Recall's read requests no eligibility. The flag, its producers, the history filter and every other read's obligation stand. |
| ADR-0275 §9:6 | A recalled episode's exact trigger input text is admitted to the understanding stage's rendering of it. Attached context and every other field stay excluded from every model input. |
| ADR-0276 §1:5 | The stage also reads what recall kept. It still reads no goal, attempt, plan, context-provider state or memory from any other read. |
| ADR-0276 §2:5 | `UnderstandingReferent.kind` gains `memory`. The existing kinds stand. |
| ADR-0276 §3:3 | A third label sequence, `M`. The rule that no label survives the call stands. |
| ADR-0276 §5:1 | Recall's read runs before understanding. Understanding still runs before association, and before every other relevance read, episodic supplement and `Planner.plan` call. |
| ADR-0280 §3:5, §4:1–§4:3 | The recall decision, `recall`, `not_recalled` and its row are added. No other member, row or order changes. |
| ADR-0280 §5:2 | The fixed default does not apply to a failed or timed-out result a failure-tolerant stage returns while the pass's deadline stands. It applies in every other case. |
| ADR-0280 §7:1 | `schema_version` becomes `Literal[4]`. `stages`, `stages_elided` and their validators stand. |
| ADR-0217 §2:5 | The predicate is applied at one further site, recall's records. Every other part of §2 stands. |

> **Normative.** ADR-0237, ADR-0276 §4's episode window and its
> selector, ADR-0276 §8, and ADR-0280 §2 remain binding as this decision reads
> them, and nothing above is a replacement of any of them. The loop's own
> relevance reads before planning are unchanged.

## Consequences

- Every activation's episode says what long-term memory was brought to it, and
  whether recall found nothing or failed, readable after the memory is deleted.
- Understanding can settle a reference from a long-term memory and cite it.
- The recall record takes items from more than one source, so recall cued by
  understanding and candidate stories add to it rather than reshape it.
- A failure-tolerant stage exists in the controller, so a later stage that
  should degrade rather than stop has a mechanism.
- A store written before this decision is refused at startup, as ADR-0280's was.
- Understanding's prompt, every activation kind's recorded path, the processing
  record's shape and the wire protocol change.

**Left to later decisions:**

- **Candidate stories.** Once stories exist, recall suggests the stories an
  activation might belong to, one or several, and understanding chooses. They
  come from two places, both link-following rather than extra searches: the
  stories of the short-term windows' episodes, which reach short replies such as
  "yes", and the stories of the episodes the search found, which reach an older
  matter named in the words. This is expected to be how short inputs reach
  long-term memory.
- **The recall hook**, including recall cued by understanding. ADR-0280's
  controller runs one stage at a time and each at most once, so the hook needs a
  stage that runs alongside the others and the no-progress limit that replaces
  the loop guard.
- **Preferences and procedural memory.**
- **Forgetting copies already recalled into episodes.**
- **Audience and provenance done properly.**
- **Retiring `model_eligible`**, which only the loop's own reads and the
  conversation history will still request.
- **Folding the loop's own relevance reads into recall**, with planning's
  reshaping.

## Alternatives considered

- **Recall inside the understanding stage.** Fewer moving parts, but the record
  could not tell a failed recall from a failed understanding, and the hook
  needs recall as its own stage. Rejected.
- **One band-neutral search**, which the proposal had. Rejected under ADR-0072
  §5: higher-scoring inferences could fill the three slots and displace an
  assertion.
- **A second search cued by the channel window.** Rejected: understanding
  already reads the window, and the search mostly adds loosely related items.
- **A thick first recall**, around 8 items and no threshold. Rejected: on a
  short input most of it is noise understanding has to read past.
- **One threshold constant.** Rejected: scores from different embedders are
  not comparable.
- **Recall excluding the windows' episodes itself.** It would make recall
  depend on how each channel builds its window. Rejected: understanding skips
  the duplicates when it renders, and recall stays independent of the
  windows. A duplicate costs one of recall's few slots, which is accepted.
- **One referent kind `memory` for everything recalled, episodes included.**
  Rejected: a recalled episode and a window episode are the same thing, and the
  recall record already says how an item was found.
- **Recording only the found ids.** Rejected: the record would be unreadable
  once a memory is deleted.
- **Letting a failed recall end the pass**, ADR-0280 §5:2's default. Rejected:
  the input can be understood without memories, and a broken store would stop
  every activation.
- **The stage catching its error and returning `done`.** Rejected: the stage
  record would say `done` for a recall that failed.
- **Recall only on some channels.** Rejected: it would make recall depend on
  the channel type. If one channel's volume ever makes the cost matter, that is
  a readiness rule added later.
