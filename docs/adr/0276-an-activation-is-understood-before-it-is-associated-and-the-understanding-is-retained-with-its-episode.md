# 276. An activation is understood before it is associated, and the understanding is retained with its episode

- Status: Proposed
- Date: 2026-09-22
- Scope: [M37](https://github.com/leonapivato/ai-assistant/milestone/4), [#2544](https://github.com/leonapivato/ai-assistant/issues/2544).
- Dependency: ADR-0274, ADR-0275 and their milestones M35 and M36.
- Authorization: the owner directed this draft on 2026-09-22 from the implementation proposal recorded on #2544, after ruling its tradeoffs and exit demonstrations there on 2026-09-21. The dispatcher assigned the next available number, 0276. That authorizes drafting and numbering, not ratification or implementation.
- **Partially supersedes** [ADR-0274](0274-channel-input-and-reply-contract.md) — **one scope.** §5's third clause, *"The first conversational conversion does not insert supplied context into prompts, memory, conversation history, or authority records; its acceptance obligation is intact delivery to processing, not a new interpretation or reference-resolution behavior"*, in its **prompt** and **reference-resolution** halves alone: the understanding stage of §5 below renders supplied context into its own prompt as quoted data and resolves the input's references against it. Supplied context still reaches no memory, no conversation history and no authority record; §5's other three clauses — the orchestration-local resolved carrier, the separation from `ConversationLifecycle.history`, and *"a source label, claimed speaker, or replied-to item does not establish an assistant-authored message, an owner instruction, or permission"* — bind entire and are the floor §5 below is built on.
- **Partially supersedes** [ADR-0275](0275-an-episode-records-one-activation-after-processing-ends.md) — **four scopes, each narrow.** **§1's exclusion list, in one item**: *"automatic cross-channel continuity"* is no longer excluded, because §4 below reads a bounded window of recent episodes across channels into one model call; §1's other exclusions (live activation log, phase/tool history, scheduler, production channel, goal association policy, observer scheduling, archive retrieval by a model) stand entire. **§4's `EpisodeProcessingRecord` field set and its `ProcessingReason` value list, in the additions alone**: the record gains §7 below's three members and `schema_version` becomes `2`; the reason list gains `understanding_failed`; every existing field, value and validator stands. **§7's rule *"All automatic model-facing episodic reads request eligibility `True`"*, for one consumer**: the window read of §4 below requests no eligibility, because the flag exists so that pre-M36 model reads keep seeing what they saw, and a window that hid newly captured events could not do what §4 exists to do; every other automatic model-facing read still requests `True`, and §7's flag, its history filter and its legacy projections stand entire. **§9's last-but-one clause, for one consumer and one field**: *"The raw input/context in the processing record and new inspection-only material retain §7's exclusion from automatic model inputs … Admitting this additional material to those paths requires a separate contract decision"* — this is that decision, and it admits the trigger's **exact input text or transcript** to the window of §4 below and nothing else: the attached context recorded on an episode's trigger stays excluded from every model input, as do the record's other fields. §10, §11 and §12 are read, not amended: `episodes` and `get_many` are the reads §4 below composes and they still invoke no model themselves, and §12's fresh-state cutover and format marker are the mechanism §7 below rides.
- **Partially supersedes** [ADR-0217](0217-a-record-carries-who-may-receive-it-and-a-model-may-only-narrow-it.md) — **one scope.** §2's clause *"The rule is applied at the sites the channel's audience is read today, and at no new site"*, in the *no new site* half alone: §4 below applies the same record-level predicate at one further site, over the stored records of the understanding stage's two windows, ahead of that stage. The clause's other half stands — it is still *"one further field read in the predicate ADR-0199 §3 and ADR-0204 §3 are already applied by"*, and the new site *"creates no stage, no seam, no store call and no second pass"* of the predicate's own — and every other clause of §2, its set rule, its conjunct with ADR-0199 §3, its reduction to two audiences, its withholding-at-supply rule and its composition with ADR-0210 §1, binds entire and is what §4 below applies.

## Context

M37's unit is the understanding of one activation: what an incoming input means,
what it refers to, how it relates to what the assistant has recently seen, how
each of those readings is grounded, and what remains unresolved. The owner's
scope on #2544 fixes what that understanding is and is not. It reads two
short-term sources — the recent context the channel supplies, and a bounded
window of the assistant's own recent episodes across channels — and nothing
else. It sets no objective, retrieves no long-term memory, chooses no
clarification and authorizes nothing. It is provisional, and its versions are
retained with the episode. The owner intends to redesign everything that runs
after it, so this decision shapes the stage as a self-contained thing and
wires no consumer of what it produces.

The baseline inspected for this draft is `484f5f2c`, the tree on which the owner
ruled M35 and M36 accepted. At that tree no understanding step exists before
goal association. `Engine._run_turn` routes the raw utterance, reads the
conversation tail through `ConversationLifecycle.history`, strips the request
once and calls `Engine._associate`, which reads the raw request and a projection
of the conversation's candidate goals. `LearningLoop._goal_from` copies the
stripped request verbatim into revision 1 of the goal's interpretation, on
ADR-0249 §3's rule that no model authors revision 1. The relevance read and the
episodic supplement query `goal.statement`, and the planner's own understanding
arrives with its plan in one `PlannerOutput` (ADR-0249 §7). On a continued turn,
therefore, everything after routing keys off the overarching goal's current
outcome rather than off anything derived from this message — which is the
behaviour #2544's fifth responsibility names: *"later processing actually
consumes this understanding, rather than independently reconstructing meaning
from the raw message or reverting to the overarching goal"*.

The channel context M35 admits is carried but never read by conversational
processing. `Engine.converse` builds a `ChannelInput` whose `context` is the empty
default, and ADR-0274 §5 binds the first conversion not to insert supplied
context into prompts. Only `InformationalEventStage` reads supplied context, and
it makes one completion over the raw event and that context to produce a
summary.

No recency-ordered, model-facing read of episodes exists. The episodic supplement
is relevance-ranked against the goal statement (ADR-0158). `MemoryStore.episodes`
is a recency-ordered cross-channel enumeration, added by ADR-0275 §10 for owner
inspection, whose rows carry positions and no text; `MemoryStore.get_many` reads
records by id. ADR-0275 §7 sets `model_eligible` false for newly captured
events, pre-result failures, interruptions and no-words speech so that the
pre-M36 model reads keep seeing exactly what they saw, and requires every
automatic model-facing episodic read to request eligibility. ADR-0275 §9 keeps
the trigger's raw input and attached context out of automatic model inputs and
names *"a separate contract decision"* as the route by which that material could
reach a model path.

Routing already makes one model call per conversational pass
(`RoutingStage.route`), and a taken route ends the pipeline there (ADR-0197
§1). Every spoken turn is treated as a turn on a channel of unbounded audience
(ADR-0250 §15, ADR-0200 §3): it builds no candidacy, associates to no stored
goal, and no stored interpretation reaches any stage of it.

The owner's rulings on #2544, recorded 2026-09-21, fix four tradeoffs this
decision takes as given. The channel window has no new ceiling: a channel
supplies its context under M35's payload limit (ADR-0274 §8), which refuses
rather than truncates, and the assistant keeps no per-channel history table. A
mechanical failure of the understanding call fails the activation after the
provider stack's existing retry; there is no degraded, invented understanding.
The associator and speaker attribution are not questions of this stage. And a
channel item and an episode carrying the same identifier are one exchange,
rendered once. The owner further directed, on 2026-09-22, that the legacy
eligibility flag not filter the window, that the planner's goal-oriented
`PlannerOutput.understanding` never be converted into an activation
understanding, that no interpreter Protocol be introduced, and — on
2026-09-22, confirming it — that this decision wire **no** downstream consumer
at all: what runs after the stage is subject to the redesign, and the third exit
demonstration on #2544 is read against the retained record rather than against
a consumer.

## Decision

### 1. Status, scope and terminology

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one
> tree and the owner's authorization to ratify stands; an assigned number or a
> green review alone does not change its status.

> **Normative.** No implementation, canonical fake included, implements these
> contracts until this numbered ADR has merged `Accepted` under ADR-0015 §5.
> This draft changes no production code and dispatches no lane.

> **Normative.** An **activation understanding** is the reading of one
> activation's input: its meaning, the references the input makes and what they
> resolve to, the relationships between the input and recently seen material,
> the ground of each of those readings, and the matters the reading leaves
> unresolved. It is owned by the activation. It is not a goal, not a revision of
> a goal's interpretation, not a plan, not a question and not an authorization,
> and no clause of this decision makes it any of those.

> **Normative.** The **understanding stage** is the orchestration stage that
> produces an activation understanding. It is not a Protocol, and `core/protocols.py`
> gains no member for it. It is a stage of the same kind as `RoutingStage` and
> `InformationalEventStage`: an orchestration-local class holding an injected
> `ModelProvider` and nothing else, tested by scripting that provider's canonical
> fake.

> **Normative.** The understanding stage receives no goal, no candidate goal, no
> attempt, no plan, no retrieved memory and no context-provider state, and its
> prompt renders none of them. It reads the activation's input and the two
> windows §3 and §4 define, and nothing else.

**Why no Protocol.** The proposal recorded on #2544 first placed the
implementation in `planning/`, which would have forced a contract in `core` for
`orchestration` to reach it. The owner ruled the Protocol out: routing and the
informational-event stage are the precedent for a single model call rendered
from an orchestration-local brief, neither has a Protocol of its own, and a
contract with one implementation that the phase redesign may relocate is a
contract paid for before it is needed.

### 2. Types

> **Normative.** Add the following to `core/types.py`. New models are frozen
> pydantic models with `extra="forbid"`; the tables define complete field sets;
> literal tags default to their listed values and other defaults are explicit.
> Reuse the existing `NonBlankEncodableText`, `EncodableText`, `Identifier` and
> `UtcInstant` validators.

| Enum | Complete values |
| --- | --- |
| `UnderstandingGround` | `stated` — the input says it; `supplied` — a supplied item the reading names says it; `inferred` — neither: the stage judged it |
| `UnderstandingOmission` | `routed` — a taken route ended the pass before the stage (§5); `no_text` — speech yielded no words or transcription failed; `no_input` — the activation carries no input to understand (a `RecordedResumeTrigger`); `failed` — the stage raised (§6); `not_reached` — the pass ended before the stage was entered for any other reason: cancellation, deadline expiry, or a failure ahead of it (§5) |
| `UnderstandingProducer` | `interpretation` — the understanding stage of this decision |

| Model | Fields |
| --- | --- |
| `ProposedReference` | `phrase: NonBlankEncodableText`; `labels: tuple[str, ...] = ()` |
| `ProposedRelationship` | `statement: NonBlankEncodableText`; `labels: tuple[str, ...] = ()`; `ground: UnderstandingGround` |
| `UnresolvedMatter` | `matter: NonBlankEncodableText`; `why_it_matters: NonBlankEncodableText` |
| `ProposedActivationUnderstanding` | `meaning: NonBlankEncodableText`; `meaning_ground: UnderstandingGround`; `meaning_labels: tuple[str, ...] = ()`; `references: tuple[ProposedReference, ...] = ()`; `relationships: tuple[ProposedRelationship, ...] = ()`; `unresolved: tuple[UnresolvedMatter, ...] = ()` |
| `UnderstandingReferent` | `kind: Literal["input", "channel_item", "episode"]`; `id: EncodableText \| None = None`; `source: NonBlankEncodableText \| None = None`; `excerpt: EncodableText` |
| `UnderstandingReference` | `phrase: NonBlankEncodableText`; `referents: tuple[UnderstandingReferent, ...] = ()` |
| `UnderstandingRelationship` | `statement: NonBlankEncodableText`; `referents: tuple[UnderstandingReferent, ...] = ()`; `ground: UnderstandingGround` |
| `ActivationUnderstanding` | `version: int` in `[1, 2**31)`; `recorded_at: UtcInstant`; `producer: UnderstandingProducer`; `meaning: NonBlankEncodableText`; `meaning_ground: UnderstandingGround`; `meaning_referents: tuple[UnderstandingReferent, ...] = ()`; `references: tuple[UnderstandingReference, ...] = ()`; `relationships: tuple[UnderstandingRelationship, ...] = ()`; `unresolved: tuple[UnresolvedMatter, ...] = ()`; `grounding_dropped: int = 0` in `[0, 2**31)` |

> **Normative.** The three enums are closed and are **added to and never
> renamed**, on `Ground`'s own rule (ADR-0249 §1 as `core/types.py` records it):
> no later ADR removes a member, renames one, gives one a second spelling, or
> replaces the enum with a differently named one for the same question.
> `UnderstandingProducer` has one member because this decision ships one
> producer; the phase redesign adds members rather than reusing this one.

> **Normative.** `ProposedActivationUnderstanding` is what the model produces
> and is the whole of what it produces. It carries **no identifier, no
> timestamp, no version and no producer**: a label in it is a string of §3's
> label scheme meaningful only within the call that rendered it, and the model
> neither invents record identifiers nor authors what orchestration assigns.

> **Normative.** `ActivationUnderstanding` is the recorded form. `orchestration`
> assigns `version`, `recorded_at` and `producer`, resolves every label into an
> `UnderstandingReferent` (§3), and copies `meaning`, `meaning_ground`,
> `unresolved` and each element's texts and ground unchanged. It carries no
> goal id, no attempt id, no plan id and no label. **It crosses no model-facing
> seam under this decision**: no consumer is wired (§8), and a later decision
> that hands it to a model owes it a projection carrying no identifier, on
> ADR-0226 §3's namer rule — *"No record identifier is rendered to a model, and
> none is accepted from one"* — and on ADR-0249 §9's ground that such
> containment is *"a property of the types rather than a rule a planner is
> trusted to keep"*.

> **Normative.** An `UnderstandingReferent` names what a label resolved to:
> `kind="input"` with `id=None` for the activation's own input; `kind="channel_item"`
> with `id` the item's `item_id` (which may be `None` where the item carries
> none) and `source` the item's `source`; `kind="episode"` with `id` the
> episode's stored `MemoryBase.id` **exactly as stored** — a blank or
> whitespace-distinct address included, on ADR-0275 §10's rule — which is why
> `id` is an `EncodableText` and not an `Identifier`; and `source` the rendering
> of its channel.
> `excerpt` is a bounded prefix of the referent's rendered text, at most 240
> characters, taken by `orchestration` from the material it rendered and never
> from model output. A referent is intelligible after restart from these fields
> alone; nothing resolves `id` on read, and a dangling `id` is an ordinary state.

> **Normative.** A `supplied` ground names its source. `ActivationUnderstanding`
> validates that `meaning_ground=supplied` implies a non-empty
> `meaning_referents` and that a relationship with `ground=supplied` carries a
> non-empty `referents`; a record that says `supplied` and names nothing is
> refused by its type. `ProposedActivationUnderstanding`
> validates **neither**: a proposal's `supplied` with no label is a grounding
> defect of §6's, repaired once and then recorded as `inferred`, and never a
> parse failure that fails the activation.

**Why the recorded and the proposed forms are two types.** A model output that
carried a version would author what orchestration owns, and a record that
carried labels would persist a string meaningful only inside one call. ADR-0249
§6 already places the revision number, `raised_by` and `recorded_at` with
deterministic code and ADR-0226 §3 already forbids persisting a label; the split
here is those two rules applied to a new record.

### 3. The channel window

> **Normative.** The **channel window** of an activation is the recent context
> its channel supplies, in supplied order. For a channel other than the
> conversation channel it is exactly `ChannelInput.context.history` followed by
> `ChannelInput.context.reply_to` where present. For the conversation channel it
> is the conversation's tail as `ConversationLifecycle.history` already reads it
> for the pass, oldest first, each record rendered as one item carrying the
> user's half and the assistant's half on ADR-0221's existing rendering, with
> the item's identifier the record's stored `MemoryBase.id` and its source the
> conversation channel. Nothing is written into the trigger's `context` to
> produce it: `RecordedChannelTrigger.context` records what the channel
> supplied and nothing this stage rendered.

> **Normative.** The channel window has no ceiling of this decision's own. A
> channel supplies what it supplies under ADR-0274 §8's payload limit, which
> counts attached context and refuses rather than truncates; the conversation
> tail is the replay bound the store already applies. The assistant keeps no
> per-channel history table and no per-channel count, and the stage takes the
> window as it arrives.

> **Normative.** The label of the item at 1-based index *n* of the channel
> window is the ASCII string `H` followed by *n* in decimal with no padding.
> The label of the episode at 1-based index *n* of §4's episode window is the
> ASCII string `P` followed by *n* in decimal with no padding. The activation's
> own input carries no label; a reading grounded in the input alone is
> `stated`. This is ADR-0226 §3's scheme applied to two further sequences on a
> call of its own: both sides derive the label from the sequence the stage
> rendered, neither consults the other, **no label survives the call and none
> is persisted as a reference**.

> **Normative.** A label outside the rendered sequences resolves to nothing. A
> string that does not match the form, an *n* below 1 or beyond the sequence's
> length, and a label of the form of a sequence the call did not render each
> resolve to nothing rather than being parsed, repaired or case-folded. What
> becomes of a proposal carrying such a label is §6's.

> **Normative — the same exchange in both windows.** An episode of §4's window
> whose stored `MemoryBase.id` equals the identifier of an item of the channel
> window is **one exchange**. It is rendered once, as the channel item under its
> `H` label, annotated as also present in the episode window; it takes no `P`
> label and is not counted toward §4's bound. A reading grounded in it names one
> referent, never two.

> **Normative.** Every span of the channel window reaches the model as quoted
> source data under ADR-0098 §2: its attribution is derived from the data the
> stage holds — the item's `source`, the record's channel, which half of an
> exchange it is — and never from the text; no span is presented as a system
> instruction, an assistant message or the user's own words; and a source label,
> claimed speaker or replied-to item establishes nothing, on ADR-0274 §5's
> fourth clause, which stands.

> **Normative.** A channel may supply no context, and the conversation tail may
> be empty. A missing window is rendered as missing. The stage does not
> compensate by retrieval, by a wider tail, by another channel's context or by
> an episode search; an input the assistant cannot place is understood as one
> it cannot place, and §4's window is the only other material it sees.

**Why the conversation channel's window is the tail and not a filled
`context`.** The owner's ruling on #2544 was that the conversation adapter
supplies its items from the hub-owned store with each item's id equal to the
turn's episode id. ADR-0275 §4 records the trigger's attached context raw in
every episode, so producing those items by filling `ChannelInput.context` would
persist the last twenty turns of the conversation inside every episode of it.
Rendering the tail the pass already reads gives the same window with the same
identifiers and writes nothing new, and it leaves ADR-0274 §5's second clause —
supplied context neither replaces nor duplicates the store history read — intact
rather than superseded.

### 4. The episode window

> **Normative.** The **episode window** of an activation is a bounded set of
> the assistant's recent episodes across all channels, produced by one
> orchestration-local **episode selector** that the composition root wires
> into the stage as it wires the model provider. The stage reads no store
> itself: it receives the selector's records, in the selector's order, and that
> order is the rendering order and the `P` label order. `core/protocols.py`
> gains no member for the selector and `MemoryStore` gains no signature.

> **Normative — what every selector must satisfy.** A selector returns a set
> bounded by a composition-root constant `UNDERSTANDING_EPISODE_LIMIT`, beside
> `ai_assistant.app.composition.RETRIEVAL_LIMIT` on ADR-0158 §5's rule, with
> initial value **10**; reads across all channels with no channel filter;
> requests no eligibility; reads episodic records and nothing else; invokes no
> model; and ranks nothing by relevance to a goal, a request or an
> understanding. Its records pass through the disclosure predicate below
> before the stage renders any of them. `ai_assistant.core.config.Settings`
> gains no field for it.

> **Normative.** The initial selector is **recency by occurrence**: the
> `UNDERSTANDING_EPISODE_LIMIT` most recent episodes by `(occurred_at,
> episode_id)` descending, taken from `MemoryStore.episodes` (ADR-0275 §10)
> with no channel and no status filter and fetched by `MemoryStore.get_many`.
> No horizon on age is applied: each episode renders with its `occurred_at`,
> and how much weight a day-old episode carries is the stage's instruction and
> the model's reading, not a cut.

> **Normative.** Within the walls above, the selection method is the
> composition root's choice, changed on evidence from live runs — a different
> bound, a per-channel mix, a size budget, a different order — by wiring a
> different selector, and such a change amends no clause of this decision and
> owes it no supersession. A selector that leaves those walls — one that filters
> by eligibility, ranks by relevance, invokes a model or reads beyond episodes —
> is a new decision.

> **Normative.** The window requests no eligibility. Episodes ADR-0275 §7
> marks ineligible — newly captured events, pre-result failures, interruptions
> and no-words speech — are in the window on the same terms as any other, which
> is the one consumer ADR-0275 §7's rule is superseded for, above. Every other automatic
> model-facing episodic read still requests eligibility `True`.

> **Normative.** Each episode of the window is rendered from an explicit
> projection and never by serializing the record. The projection is: its
> channel (type and instance) or, absent a processing record, its capture
> modality; its `occurred_at`; its input — the trigger's exact payload text or
> transcript where the record carries a processing record, and otherwise the
> record's `content`; its response — `outcome`, or that there was none; its
> processing status and reason where recorded; and, where the record's
> processing record carries §7's history, the **latest** version's `meaning`,
> `meaning_ground` and `unresolved` texts, rendered as provisional — as what
> the assistant *understood then* and never as an established fact. Input and
> response are each cut to a bounded prefix, the bound a composition-root
> constant `UNDERSTANDING_EXCERPT_CHARS` with initial value **2000**, and the cut
> is disclosed in the rendering.

> **Normative.** The projection renders **no** attached context recorded on the
> episode's trigger, no `ActivationLinks`, no earlier understanding version's
> references or relationships, no `Capture`, no placement, no provenance
> evidence and no identifier. The trigger's exact text is the one raw field this
> decision admits, above; everything else ADR-0275 §9 excludes stays excluded.

> **Normative.** Every span of the episode window reaches the model as quoted
> source data under ADR-0098 §2, attributed from the record — which channel,
> which half, whether it was a report or a request — and never from the text.
> An episode of an event channel is rendered as a **report received**, never as
> something the user said or the assistant did.

> **Normative — the stored records of both windows pass through the disclosure
> predicate before the stage renders them.** The conversation tail's records and
> the episode window's records are `MemoryRecord` values, and each is admitted
> to the stage only where the record-level predicate the pass's supply already
> applies to its `memories` — ADR-0199 §3's placement test as ADR-0204 §3 and
> ADR-0217 §2 extend it, the function `orchestration.disclosure` applies per
> record — admits it for the pass's audience. It is invoked over the records
> alone: no `CurrentContext` is assembled for it, none is passed, and context
> assembly stays where the baseline has it, inside the loop after association.
> On a channel of unbounded audience the predicate withholds every
> `OWNER`-placed record from the stage, tail record included, and the
> withholding fires no deflection and sets no `withheld` fact, on ADR-0217 §2's
> own composition with ADR-0210 §1: *"one the supply holds only because it
> stands in the conversation's own recent turns is withheld and fires nothing"*.
> On a channel of bounded audience the predicate withholds nothing. A withheld
> record reaches no rendering, no label, no referent and no version.

> **Normative.** A supplied channel item is not a record. It carries no
> placement, no `about_person` and no provenance, the channel that supplied it
> to this pass already holds it, and it passes to the stage as supplied, on
> ADR-0274 §5's fourth clause — it establishes nothing — and on ADR-0098 §2 —
> it is quoted. No placement or provenance is fabricated for it, and the
> disclosure predicate is not evaluated over it.

> **Normative.** This is the one further site of ADR-0217 §2's *no new site*
> clause, superseded above in that half alone: the same predicate, over one
> further sequence of records, with no predicate, seam, store call or second
> pass added.

> **Normative.** An informational-event pass is a pass of **bounded** audience
> for this purpose: its result returns to the authenticated caller of `receive`
> and, on ADR-0274 §7, *"the submitting test adapter inspects it as an
> operational result and sends no message back to the source or to a user
> interface"*. The engine holds a `BoundedAudienceSupply` for such a pass and
> applies it exactly as above; nothing is withheld, and the evaluation is made.

> **Normative — a turn on a channel of unbounded audience takes no episode
> window.** On the operation ADR-0250 §15 names (`converse_spoken`, as ADR-0200
> §3 declares it) the stage receives the channel window alone, and that window
> renders each tail record's two halves and **no** stored understanding version.
> Nothing in the record of another channel's episode, and no earlier
> understanding, reaches any stage of such a turn — which is ADR-0250 §15's
> rule read over the one new carrier this decision adds. The understanding of
> the turn's own input is produced and consumed exactly as on any other turn.

**Why an existing read and not a new member.** ADR-0158 §5 declined a time-range
read for the episodic supplement because its consumer's questions are topical.
This consumer's question is recency, and ADR-0275 §10 has since put a
recency-ordered cross-channel enumeration on the contract for inspection. The
initial selector is that enumeration and the batch read that already exists,
composed in `orchestration`; a third member would be a second spelling of an
ordering the contract already has.

**Why the method is a selector and not a clause.** The owner directed that the
window's rule be easy to adjust in method and not only in value. Ten by recency
is a first guess with no measurement behind it, and the exit run is the first
evidence. Fixing the method here would make every adjustment a supersession;
fixing the walls instead — bounded, cross-channel, eligibility-blind,
disclosure-filtered, model-free, relevance-free — makes an adjustment a wiring
change and keeps what this decision actually cares about binding. A selector is
one function with one consumer in one subsystem, which is why it is not a
Protocol.

**Why no horizon.** A cut by age empties the window exactly when it matters: a
trip discussed on Monday and a closure reported on Wednesday are two days apart
and still the two most recent things that happened. The timestamp is rendered,
so the model has what a horizon would have used and loses nothing a horizon
would have hidden.

**Why the eligibility flag does not apply.** ADR-0275 §7's own words: the flag is
set false for *"newly captured events, pre-result failures, interruptions, and
no-words speech"* so that *"the new exclusion is for previously uncaptured
failure-only material, not a removal of existing conversational evidence"*. It
is a compatibility fence around the reads that existed before M36. This stage
did not exist before M36, and the first exit demonstration on #2544 — a closure
reported on the event channel, related to a camping conversation through the
episode window alone — needs exactly the events that fence hides.

### 5. Placement

> **Normative.** The understanding stage runs on every conversational pass of
> `converse`, `converse_streaming` and `converse_spoken`, and on every
> informational-event pass, **after** the routing stage has declined and the
> conversation is resolved, and **before** `Engine._associate` and before any
> relevance read, episodic supplement or `Planner.plan` call of the pass. On an
> informational-event pass it runs in `Engine._dispatch_channel`, after the
> event input is resolved and **before** `InformationalEventStage.process` is
> invoked; the event stage itself is unchanged by this decision, reads no
> understanding and still originates its one completion under ADR-0274 §7. On
> every pass the stage runs inside
> the pass's existing deadline and adds no budget, no setting and no second
> deadline.

> **Normative.** A route that is taken ends the pipeline where ADR-0197 §1 ends
> it, and the understanding stage does not run. The pass's processing record
> carries `understanding_omitted=routed` (§7), which is distinguishable from a
> failed understanding and from a pass the stage never applied to.

> **Normative.** Speech that yields no words and speech whose transcription
> failed keep their existing capture and outcomes under ADR-0200 §4 and
> ADR-0275 §4, §5; the stage does not run and the record carries
> `understanding_omitted=no_text`. No understanding is fabricated for an input
> that has no text. `AssistantEngine.resume` and every other activation carrying
> a `RecordedResumeTrigger` record `understanding_omitted=no_input`.

> **Normative.** A pass that ends before the stage is entered for any reason
> the three values above do not name — a cancellation acknowledged before or
> during routing, a deadline that expired ahead of the stage, a failure in
> conversation resolution or any other step ahead of it — records
> `understanding_omitted=not_reached`. The classification is by where the pass
> ended and never by inference from its text: `routed`, `no_text` and `no_input`
> each name a branch the pass took, `failed` names the stage's own raise, and
> `not_reached` is everything that ended ahead of the stage's entry. A pass that
> recorded version 1 records no omission whatever ended it.
> **Normative.** The stage is entered exactly once per activation, makes at most
> two completions (§6), and records exactly one `ActivationUnderstanding` at
> version 1 with `producer=interpretation` on the activation's state before
> `Engine._associate` is called. A pass that ends between that record and
> capture — an `UNDECIDED` association, a raised question, a refusal, a failure
> downstream — still captures the version §7 requires: capture reads the
> activation's state and not the branch the pass ended on.

> **Normative.** The stage neither reads nor writes the goal. Goal association,
> `GoalCandidacy`, `LearningLoop._goal_from`'s revision 1 and ADR-0249 §3's rule
> that no model output authors it are unchanged by this decision, and so are the
> relevance read and the episodic supplement's query (ADR-0249 §11), the
> question path (ADR-0250 §6–§8) and the attempt phases (ADR-0249 §6). This
> decision amends no clause of ADR-0249 or ADR-0250; the reads it adds are
> stacked beside them.

**Why routing stays ahead.** The routing stage already makes one completion per
pass over the raw utterance and declines on any failure. A stage ahead of it
would put a second completion in front of every control utterance, for an
understanding that a taken route then discards. Context-dependent control
requests — *"cancel that"* — are therefore routing's or nobody's on this
decision, and the six-phase ruling that placed them in a "phase 1" is
explicitly deferred to the phase redesign rather than carried here; #2544
records that deferral.

**Why the stage is before association rather than inside the loop.** The
understanding is the activation's and not the goal's, and the loop holds the
goal. Placing the stage before `_associate` is what lets a pass that never
reaches the loop — the undecided one, the one that raised a question — still
carry an understanding, and it is what keeps the stage goal-blind by
construction rather than by a rule its prompt is trusted to keep.

### 6. The call, its validation and its failure

> **Normative.** The stage renders one prompt from the input and the two
> windows under ADR-0098 §2, instructs the model to produce one
> `ProposedActivationUnderstanding` — a meaning and its ground, the input's
> references each resolved to labels, the relationships each grounded in labels
> or marked inferred, and the unresolved matters with why each matters — and
> makes one completion through the injected `ModelProvider`, which is the
> application's ordinary route and carries the provider stack's existing retry
> policy under ADR-0011. The instruction states that an unresolved matter
> carries **no** recommended lookup, question, action or routing, and that a
> reading the windows do not support is `inferred` and not `supplied`.

> **Normative.** The stage validates the completion in this order: the output
> parses as one `ProposedActivationUnderstanding`; every label resolves under
> §3; every element proposing `supplied` — the meaning through
> `meaning_labels`, a relationship through `labels` — names at least one
> label. Where the output fails to parse, where any label resolves to nothing,
> or where a `supplied` element names no label, the stage makes **exactly one**
> further completion carrying the first output
> and a code-owned statement of what was wrong — the parse failure, or the
> labels that resolved to nothing and the sequences that were rendered — and
> validates that second output the same way. There is no third completion.

> **Normative.** A second output that does not parse raises
> `UnderstandingError`, a new `AssistantError` subclass in `core/errors.py`
> with only the standard message constructor and no content-bearing field. A
> `ModelError` the provider stack raises after its own retry propagates
> unchanged. Either ends the activation as a failure: no response is composed,
> no goal is associated, and the processing record carries
> `understanding_omitted=failed` with the status and reason §7 assigns. The
> stage never substitutes an empty, default or invented understanding for one
> it could not obtain.

> **Normative.** A second output whose labels still include one that resolves to
> nothing, or that still proposes `supplied` on an element naming no label, is
> **recorded**, not refused: each unresolvable label is dropped and counted in
> `grounding_dropped`; a `supplied` element naming no label is counted once
> there as well; and the meaning or a relationship that **proposed `supplied`** and is
> left with no resolved referent is recorded with `ground=inferred` and no
> referent. An element that proposed `stated` or `inferred` keeps the ground it
> proposed whatever became of its labels — the input carries no label by §3, so
> a `stated` meaning names no referent and is downgraded by nothing. A reference
> whose labels all dropped is recorded with no referent. **No dropped or absent
> label becomes a grounded claim**: a referent is recorded only for a label that
> resolved, and a ground of `supplied` survives only on an element that still
> names at least one referent, which §2's validator on the record enforces
> by type.

> **Normative.** A valid understanding that carries unresolved matters, or
> whose meaning is `inferred`, or whose references resolve to nothing, is a
> **successful** understanding. It is recorded at version 1, and it is neither
> a failure nor a degradation of the pass. The
> owner's ruling on #2544 distinguishes the model failing mechanically from the
> model finding the input unclear, and the second is what this stage is for.

> **Normative.** `ProcessingReason` gains `understanding_failed`. In ADR-0275
> §5's ordered table, a pass that `UnderstandingError` ended records `failed /
> understanding_failed`, at a priority immediately below transcription failure
> and above output oversize; a `ModelError` from this stage takes the row its
> class already takes — a classified timeout records `failed / timeout`, and any
> other `failed / processing_failed`. On an informational-event pass the same
> failures, raised in `Engine._dispatch_channel` ahead of the event stage, map
> outward to `ChannelProcessingError` and `ChannelProcessingTimeoutError`
> exactly as ADR-0274 §8's partition maps that stage's own completion failures,
> and the record is the same.

> **Normative.** The stage logs stage and code-owned reason only. It logs no
> input, no window content, no model output and no exception content, on
> ADR-0275 §8's rule for capture.

**Why an unresolvable label after repair is recorded and not refused.** The
owner's ruling fails the activation on a mechanical failure — the provider is
down, the output is not the shape asked for. A label the model got wrong twice
is neither: the output is a well-formed understanding with one claim the stage
cannot ground. Failing every input on that would make the owner's own "compare
these" demonstration hostage to whether the model spelled `H3` or `H03`; hiding
it would violate #2544's requirement that invalid references never become
apparently grounded. Recording the claim as ungrounded, with the count on the
record, is the third option and the one that keeps the record honest.

### 7. Retention and inspection

> **Normative.** `EpisodeProcessingRecord.schema_version` becomes
> `Literal[2]`, and the record gains `understanding: tuple[ActivationUnderstanding, ...] = ()`,
> `understanding_omitted: UnderstandingOmission | None = None` and
> `understanding_elided: int = 0` in `[0, 2**31)`. A record carries **exactly
> one** of a non-empty `understanding` and a non-`None` `understanding_omitted`,
> enforced by validator. No reader for a version-1 record exists.

> **Normative — fresh state, on ADR-0275 §12's own mechanism.** The owner
> declared pre-M37 development state disposable, as ADR-0275 §12 records for
> pre-M36 state, and the M36 cutover to a fresh data directory has not yet been
> deployed; M37 rides that same cutover. Advance the episode-record format
> marker ADR-0275 §12 persists, so that a store written before this decision is
> refused before mutation with `IncompatibleStateError` exactly as §12 refuses a
> pre-M36 store, and its files are neither erased nor upgraded. No migration,
> backfill or version-1 read path is a deliverable, and no mixed-version path
> is required.

> **Normative.** Versions accumulate on the activation's state
> (`ActivationState`) during the pass, `version` minted one greater than the
> last recorded, and are written **once**, at capture, into the processing
> record with the rest of it. ADR-0275 §8's rules stand: no captured record is
> updated in place afterward, no model completion runs for capture, and a later
> activation has its own understanding and never rewrites an earlier episode's.

> **Normative.** The history is bounded at `UNDERSTANDING_VERSION_LIMIT`
> versions, a composition-root constant with initial value **8**. Where more
> were recorded, the tuple keeps version 1 and the latest `UNDERSTANDING_VERSION_LIMIT - 1`,
> in version order, and `understanding_elided` counts the versions dropped.
> The latest version is never elided.

> **Normative.** This decision ships one producer of a version, the
> understanding stage at version 1. Who writes a later version, what a revision
> records beyond the fields §2 fixes, and which stage reads the latest one are
> the phase redesign's decisions. A test that
> records several versions on the state and reads them back exercises the
> carrier; it is not evidence of a working revision path, and no lane claims it
> as one. `PlannerOutput.understanding` is a goal record — an outcome, its
> constraints, criteria, conditions and questions — and is **never** converted
> into an `ActivationUnderstanding` or recorded as one of its versions.

> **Normative.** The episode's canonical detail (ADR-0275 §10) carries the
> record as it carries every other field, so `assistant episode <id> --json`
> shows every retained version complete and the detail `version` digest changes
> with them. The human rendering of `assistant episode` shows, per retained
> version, its number, producer, meaning and ground, each reference's phrase
> and referent kinds, each relationship's statement and ground, and each
> unresolved matter, and shows an omission value or the elided count where the
> record carries one. Inspection invokes no model (ADR-0275 §11).

> **Normative.** Retention, deletion, export, placement and disclosure are
> ADR-0275 §9's, unchanged: the versions ride the enriched record under
> `episode_retention`, are deleted with it, are exported with it, and are
> admitted to no shared-output path this decision does not name. A recorded
> understanding grants no authority, establishes no fact, and is never read as
> the owner's instruction; it is what the assistant understood, and §4 renders
> it to a later call only as that.

> **Normative.** `EpisodicMemory.processing_record` crosses the wire (the entry
> at protocol 54), so the added fields change a shared wire-carried shape.
> Advance `PROTOCOL_VERSION` **in the same change that adds the fields**, on
> ADR-0124 §9's rule — *"The obligation is on whoever makes the change, in the
> same change"* — and maintain same-build client/server deployment under
> ADR-0084 §3's exact-match handshake. No integer is fixed here: the change
> that lands the record bumps from the figure it finds. Extend the wire
> surface/type closure and the memory and engine conformance suites with the
> shape. No compatibility shim, optional-member negotiation or lenient decode
> is added.

**Why one bounded tuple and not a separate store.** The versions are facts about
one activation, written when it ends; ADR-0275 §8's capture-once rule already
fixes where such facts go and forbids updating them later. A separate store
would need a writer fence, a deletion cascade and a retention rule of its own to
say the same thing. The bound is what keeps the record's size a function of the
activation and not of how many stages a future redesign runs.

### 8. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then
> the implementation ships as separate PRs in this order, and **every
> intermediate tree keeps capture working and refuses an incompatible store**:
>
> 1. **`core` with `wire` — additive only.** §2's types, `UnderstandingError`,
>    the `understanding_failed` reason, and §7's three record fields with
>    their defaults, with `schema_version` still `Literal[1]` and **no**
>    exactly-one validator, so every existing writer still validates; and
>    §7's `PROTOCOL_VERSION` advance with the wire surface/type closure, which
>    ADR-0124 §9 puts in the same change as the wire-carried shape it follows.
> 2. **The cutover — one change spanning `core`, `orchestration` and
>    `memory`, permitted expressly here as one mechanical unit** and as the one
>    exception this decision makes to one-subsystem-per-change: `schema_version`
>    becomes `Literal[2]` with §7's exactly-one validator; `ActivationState.processing`
>    writes `understanding_omitted=not_reached` on every capture, which is
>    true of every pass until the stage exists; and the episode-record format
>    marker in `memory` advances with its startup check and fresh-store
>    initializer, so a store written before this tree is refused before
>    mutation under ADR-0275 §12. No stage behaviour lands here.
> 3. **`orchestration`** — the understanding stage, its placement on the
>    conversational and event paths, the two windows and the episode selector,
>    the same-exchange rule, the disclosure filtering, the audience rule, the
>    activation-state carrier and capture of §7's versions and the real
>    omission values.
> 4. **`interfaces`** — the episode rendering of §7.
> 5. The live exit demonstrations.
>
> (3) and (4) each depend on (2) and not on each other.

> **Normative.** The plain tests #2544 names ride with their owners: the stage's
> parse, repair, drop-and-count and failure behaviour, the same-id rendering,
> the routed, no-text and not-reached omissions and the multi-version carrier
> with (3); the record's exactly-one validator and the store refusal with (2). The exit demonstrations
> are the three recorded on #2544 on 2026-09-21, driven end to end against a hub
> deployed from a tree carrying M35, M36 and this decision's implementation,
> with the third read as the owner amended it on 2026-09-22: both the
> comparison request and the restriction are present in the retained
> understanding as read back through `assistant episode`, and no consumer is
> demonstrated. Acceptance is recorded on #2544 with the tested revision, the
> retained understandings as read back, the residuals and the owner's explicit
> exit ruling.

> **Normative.** This decision changes no clause of ADR-0249 or ADR-0250,
> adds no member to `MemoryStore`, `ConversationLifecycle`, `AssistantEngine`
> or any other Protocol, changes no signature in `core/protocols.py`, wires no
> consumer of the understanding, adds no `Settings` field, adds no production
> channel, and implements no part of ADR-0163. Cross-conversation association,
> the per-phase processing history ADR-0249 §13 defers, the observer's reading
> of understandings and every downstream phase remain outside it.

### 9. Relationship to earlier decisions

> **Normative.** This numbered draft records its scoped replacements on each
> affected ADR's status line and in a dated header note, atomically with this
> file, under ADR-0070 §4 and ADR-0082 §1. Preserve earlier supersessions and
> every ratified body. The replacements take effect on ratification; their
> reciprocal records are required while this decision remains `Proposed`.

| Decision | Replaced scope and what remains |
| --- | --- |
| ADR-0274 §5 | The third clause's prompt and reference-resolution halves: the understanding stage renders supplied context into its prompt as quoted data and resolves references against it. Supplied context still reaches no memory, conversation history or authority record; the resolved carrier, the separation from the store history read and the no-authority-from-labels clause stand. |
| ADR-0275 §1 | "Automatic cross-channel continuity" leaves the exclusion list for the bounded window of §4 alone. Every other exclusion stands. |
| ADR-0275 §4 | The record gains `schema_version` `2`, `understanding`, `understanding_omitted` and `understanding_elided`; `ProcessingReason` gains `understanding_failed`. Every existing field, value, validator and the raw-context recording rule stand. |
| ADR-0275 §7 | The eligibility-`True` requirement on automatic model-facing reads does not bind §4's window. The flag, its producers, the history filter and every other read's obligation stand. |
| ADR-0217 §2 | The *no new site* half of its application clause: the record-level predicate is applied at one further site, over the stored records of the understanding stage's two windows. The predicate itself, its set rule, its two audiences, its withholding-at-supply rule and its composition with ADR-0210 §1 stand. |
| ADR-0275 §9 | The trigger's exact input text or transcript is admitted to §4's window. Attached context and every other raw or inspection-only field stay excluded from every model input; retention, deletion, placement, disclosure and authority rules stand. |

> **Normative.** ADR-0197 §1's taken-route rule, ADR-0274 §7, ADR-0199 §1 and §3, ADR-0200
> §3 and §4, ADR-0204 §2 and §3, ADR-0210 §1, ADR-0226 §3's namer rule,
> ADR-0249 §3, §6, §7, §9 and §11, ADR-0250 §3 and §15, ADR-0158 §5, ADR-0098
> §2, ADR-0124 §9 and ADR-0011's retry policy remain binding as this decision
> reads them, and nothing above is a replacement of any of them.

## Consequences

**What becomes possible.** An input is read against what the assistant has just
seen, on its own channel and on others, before anything decides what it is for.
*"Riverside is closed"* arriving on the event channel while a conversation is
planning a camping trip is understood as a report that concerns that trip, with
its duration unresolved and no instruction in it, and that reading is on the
episode for the owner to inspect and for a later phase to build on. *"Compare
these, don't book"* is retained with both its request and its restriction on the
episode, for whichever phase the redesign wires first to read rather than
re-derive.

**What it costs.** A conversational text pass now makes four completions in
sequence — routing, understanding, planning, composition — under one deadline,
and an informational-event pass makes one more than today. The stage's prompt carries the selector's
episodes, ten under the initial selector, and the channel window, each bounded. The exit run is where the
deadline is observed; §5 moves no budget, and a lane that finds it binding
opens an issue rather than widening it in place.

**What it deliberately leaves.** No consumer of the understanding is wired:
the planner, the event summary, retrieval and the composer read exactly what
they read today, and the redesign decides which stage reads the record first.
The revision record is a carrier with one producer; the redesign decides who
revises and what a revision says.
Spoken turns see no other channel's episodes. Routed control utterances are
understood by nobody. Each is recorded here as a boundary rather than left to
be discovered as an omission.

**What would reopen this decision.** A second channel type whose items carry
their own identifiers, which needs the one-field M35 amendment #2544 defers so
that an episode remembers its item id. A phase redesign that gives another stage
a reason to revise the understanding, which takes §7's carrier and adds a
producer. Evidence from the exit run that ten by recency is the wrong selection,
which wires a different selector and moves no clause. And a decision to let
a spoken turn on the owner's own device see the episode window, which is an
audience ruling ADR-0250 §15 owns.
