# 221. An episode carries the reply, a typed disposition, and how the turn was captured

- Status: Partially superseded by ADR-0223 (§6's first clause, and within it only its first sentence — *"Capture writes the captured episode's `Provenance.derived_from_external` exactly as it does today — it is not set, and takes its `False` default"*. Capture now stamps that field, from the turn's own selection and threaded to the capture point. The remaining sentence of that clause, the whole of §6's second clause, and every other section of this ADR stand)
- Date: 2026-09-01
- Partially superseded: 2026-09-02 by ADR-0223 — **§6's first clause no longer
  holds of capture: `Provenance.derived_from_external` is stamped on the captured
  episode from `SelectionOrigin.over(turn.memories)` for the turn whose rendering
  it carries, threaded per call site and never computed at capture.** Only the
  clause's opening sentence is replaced, because only that sentence is a statement
  about *capture*; the rest of it — *"This ADR adds no mark, threads no origin
  value to the capture point, and changes no value any component computes for that
  field"* — is a statement about **this ADR**, and stays true of it. §6's second
  clause, which binds lanes implementing this ADR not to cite it as authority that
  the episode's origin is recorded, is untouched and is restated there. §13's first
  bullet is **discharged** rather than superseded: it deferred the mark *"Fired by
  whoever picks it up"*, and this is that pickup.
  [ADR-0223](0223-a-captured-episode-carries-the-externality-of-the-supply-its-turn-ran-over.md)
  §1, §3 and its closing section.
- **Partially supersedes:**
  [ADR-0074](0074-conversation-is-an-entity-and-every-turn-is-an-episode.md)
  — **§3's field role, not its argument.** §3's bullet *"Not the message:
  `EpisodicMemory` carries an `outcome`, which is a property of a completed exchange"*
  argues that the unit of capture is the turn, and that argument stands whole — a
  reply is a property of a completed exchange exactly as a phrase is. What is replaced
  is the field role the bullet assumes: `outcome` is no longer where the exchange's
  *result* is stated. §1 puts the composed reply there and §2 puts the result in a new
  `disposition` field. §4's stamps, §7's retention and §11's device-identity deferral
  are untouched; §11's observation that *"nothing on a turn records where it came
  from"* is a deferral this ADR discharges rather than a decision it supersedes, and
  §5 says so in terms.

  [ADR-0162](0162-what-the-user-tells-the-assistant-is-recorded-and-selectivity-moves-to-retrieval-and-forgetting.md)
  — **§8's first clause, and no other.** *"The observation prompt states an episode's
  `outcome` where the episode carries one"* becomes: the observation prompt states the
  phrase for the episode's `disposition` where it records one, and its `outcome` where
  it does not. §8's four remaining clauses — the whole-episode citation and the
  act/proposition boundary — bind unchanged, as do §1, §2 and the rest of that ADR.

## Context

### Where this comes from

`track:memory` (#1231), design note #1845, and the two issues it proposes to close:
#1221 (should the reply be stored, and at what fidelity) and #1314 (the
second-turn reference-back a stored reply would make possible). #1842 is the
surrounding argument for why an assistant that keeps no record of its own conduct
cannot learn from it; #1843 and milestone 21 of #1318 own the source archive this
decision deliberately does not build.

### The gap, read from the tree rather than recalled

`EpisodicMemory.outcome` today holds one of exactly sixteen constant phrases.
`orchestration/engine.py`'s `_outcome_of` returns one of eight — seven for the
members of `Disposition` and one for the no-step case — and `_routed_outcome_of`
returns one of eight, one per member of `RouteOutcome`. Both are total over their
input by `assert_never`. `Engine._capture` receives the pass's `ComposedReply` and
its docstring says what becomes of it: *"It reaches the outcome and nothing else:
what is captured is the exchange, and whether the composed answer joins the
episode is ADR-0170 §9's deferral to ``track:memory`` (#1314) rather than this
method's to decide."* The reply is in scope at the capture point and dropped
there.

The consequence is that the store holds no word the assistant said. #1845 records
the measurement against a live hub on 2026-08-30: fifty-two episodes, none
containing one.

### Five ADRs reserved this ground, and none forbids it

ADR-0170 §9 defers *"Whether the composed answer joins the episode the turn
captures"* to `track:memory` in terms. ADR-0197 §10 defers it again — *"Whether
the composed **reply** joins the captured episode is #1314's ground and is
untouched either way"* — and ADR-0197 §11, ADR-0203 and ADR-0204 each repeat the
deferral in their own "does not decide" sections. ADR-0162 §8 states the gap from
the other side: it ratifies that *"What the assistant said **independently
supports** a record of its own act"*, while the assistant's actual answer text is
captured nowhere.

### What the corpus already decides, and this ADR may not rebuild

- **Truncation is decided, the other way.** ADR-0170 §8: an answer that would
  breach the result-payload ceiling *"is that refusal — never a silent
  truncation"*. A stored prefix is therefore not on the menu.
- **The two vocabularies are mutually exclusive by ratified decision.** ADR-0197
  §1: *"A route that is **taken** ends the pipeline there. No goal is minted, no
  context is assembled, no memories are retrieved, no plan is made or persisted,
  **no step is driven**."* One field can carry both without a co-occurrence
  validator.
- **A routed result never enters a prompt** (ADR-0197 §6) and the captured episode
  carries no part of the routed account (§10). The composing stage on a routed pass
  is given exactly two enum values, so a routed reply cannot contain what §6
  withholds.
- **The episode stays textual.** ADR-0094 §8: *"Raw source material is never an
  episode."*
- **`PROTOCOL_VERSION`'s test is ADR-0124 §9's**, and two rulings on this exact
  envelope decide the two limbs this change touches: ADR-0213 §11 for a defaulted
  addition to `MemoryBase`, and ADR-0210 §8 for a change to *the value the hub
  computes* for a field whose shape is unmoved.

### Three claims in #1845 that do not survive contact with `origin/main`

Recorded here because two of them are load-bearing and a later reader would
otherwise inherit them.

1. **Episodes do cross the wire.** #1845 §3 says *"Neither ``EpisodicMemory`` nor
   ``MemoryRecord`` appears under ``wire/`` or ``service/``, so ``PROTOCOL_VERSION``
   does not move"*. `wire/envelope.py`'s version log says the opposite, and used it
   as the ground for the bump to 23: *"``MemoryBase`` and ``Provenance`` are
   wire-carried … ``TurnResult.memories`` is ``tuple[MemoryRecord, ...]``, carried
   inside ``TurnOutcome.turn``"*. The conclusion — no bump — survives, on the two
   grounds §8 below applies instead.
2. **`Disposition` lives in `core/types.py`**, beside `RouteOutcome`, not in
   `orchestration/runner.py`. The member counts are as #1845 states: seven and
   eight.
3. **Partial text is not unique to the ceiling stop.** `ComposedReply`'s docstring
   says `degraded` rides beside a non-`None` `text` *"on exactly one shape and no
   other"*, the ceiling stop. `ComposingStage.compose_streaming` and
   `compose_streaming_routed` both also reach `ComposedReply(text=answer.text,
   degraded=stopped)` after a mid-stream `ModelError`, whenever anything was
   published before it. The docstring is narrower than the code; §1 below rules over
   the code's actual shape, and the discrepancy is filed rather than fixed here.

### What made the fourth question — the channel — ripe

ADR-0074 §11 deferred recording where a turn came from, and ADR-0200 §8 and
ADR-0203 §4 each declined to add the field. The owner's direction of 2026-09-01 on
#1845 reframes it: not a `spoken | typed` flag, which a second modality would have
to *supersede*, but a record the archive decision can grow. ADR-0094 §7 is already
modality-neutral — it rules over *"source material"* rather than over audio — and
ADR-0094 §8 keeps the episode textual. So what the episode is missing is not a
`spoken | typed` flag on the record but a statement of how the material the user
supplied reached this system, in a shape a later modality extends rather than
replaces.

## Decision

### 1. `EpisodicMemory.outcome` carries the composed reply, whole

> **Normative.** Where the pass produced a reply, capture writes that reply into the
> captured episode's `outcome`, and writes it **whole**. No implementation, setting
> or later lane stores a prefix, a summary, an elision or any other lossy rendering
> of it there.

> **Normative.** Where the pass produced no reply, `outcome` is `None`. The paths on
> which no reply exists are exactly five, and they are the two shapes the engine
> already has: a pass on which `Engine._compose` returns no `ComposedReply` at all —
> a step that parked for confirmation, a routed pass that parked, and a resume driven
> from a recovered park — and a pass whose `ComposedReply` carries a `text` of `None`,
> which is a classified composition failure including the blank completion (ADR-0170
> §8) and a stream that published nothing before it stopped.

> **Normative.** Where a stream stopped after publishing, capture stores the text that
> was published. This is the whole of what the assistant said, not a prefix of
> something longer that exists elsewhere: on the ceiling stop (ADR-0173 §3) and on a
> mid-stream `ModelError` alike, `ComposedReply.text` is the text the stage emitted,
> and no continuation of it was ever composed. `ComposedReply.degraded` reports the
> pass on `TurnOutcome.reply_degraded` as it does today.

> **Normative.** No field is added to `EpisodicMemory` recording that a reply it
> carries was cut short. The record states what the assistant said, which is what the
> stage emitted; whether the pass completed is the `TurnOutcome`'s to report and is
> already reported there.

**Why the whole reply and not a prefix.** ADR-0170 §8 decided reply size the other
way for the wire, and a corpus that refuses an oversized answer at the wire while
silently clipping it at the store would be saying two things. The sharper reason is
that an assertion's meaning depends on its ending: half of *"I would not book that
flight, because…"* is a different claim from the whole of it, and a store that
half-keeps it holds a record that is worse than no record. #1221's three-way
question — whole, distilled, or a prefix — therefore collapses to two, and #1834
disposes of the distilled act.

**Why the cut stream stores its text rather than discarding it.** ADR-0173 runs the
turn beside the generator rather than inside it, so the text exists at the capture
point whatever became of the connection. Discarding it would make the episode of a
cut turn read as an exchange in which the assistant said nothing, which is false of
every one of them. What the reader lost is not repaired by the store losing it too.

### 2. The disposition becomes a closed enum in `core`, sixteen members, kept distinct

> **Normative.** `core/types.py` gains one `StrEnum`, `ExchangeDisposition`, with
> exactly sixteen members: one per member of `Disposition`, one for the no-step case,
> and one per member of `RouteOutcome`. `EpisodicMemory` gains one field,
> `disposition: ExchangeDisposition | None`, defaulting to `None`.

> **Normative.** The two vocabularies are **not normalised** into a smaller shared
> one. Where a member of each pair denotes the same fact in ordinary English —
> `EXECUTED`/`PERFORMED`, `DENIED`/`REFUSED`, and the two `AWAITING_CONFIRMATION`s —
> both members ship. No implementation or later ADR collapses a pair, and none maps
> two members onto one.

> **Normative.** The members are named so that which vocabulary a member came from is
> legible in the member itself; each member's **serialised value** is fixed here and
> not left to the implementing lane; and the sixteen are:
>
> | from | member | value | the phrase it stands for |
> | --- | --- | --- | --- |
> | no step | `NO_ACTION_NEEDED` | `no_action_needed` | `no action was needed` |
> | `Disposition.EXECUTED` | `STEP_EXECUTED` | `step_executed` | `the selected tool ran` |
> | `Disposition.DENIED` | `STEP_DENIED` | `step_denied` | `the action was refused by the permission policy` |
> | `Disposition.AWAITING_CONFIRMATION` | `STEP_AWAITING_CONFIRMATION` | `step_awaiting_confirmation` | `the action was parked for the user to confirm` |
> | `Disposition.NO_CAPABLE_TOOL` | `STEP_NO_CAPABLE_TOOL` | `step_no_capable_tool` | `no tool advertised the capability the step needed` |
> | `Disposition.AMBIGUOUS_CAPABILITY` | `STEP_AMBIGUOUS_CAPABILITY` | `step_ambiguous_capability` | `several tools advertised the capability, so none was chosen` |
> | `Disposition.INVALID_PARAMETERS` | `STEP_INVALID_PARAMETERS` | `step_invalid_parameters` | `the step's arguments did not fit the declared schema of any capable tool` |
> | `Disposition.EGRESS_UNBINDABLE` | `STEP_EGRESS_UNBINDABLE` | `step_egress_unbindable` | `the outbound call could not be described, so nothing was asked or sent` |
> | `RouteOutcome.PERFORMED` | `ROUTED_PERFORMED` | `routed_performed` | `the assistant performed the operation the user asked for` |
> | `RouteOutcome.AWAITING_CONFIRMATION` | `ROUTED_AWAITING_CONFIRMATION` | `routed_awaiting_confirmation` | `the operation was parked for the user to confirm` |
> | `RouteOutcome.REFUSED` | `ROUTED_REFUSED` | `routed_refused` | `the user declined, so the operation was not performed` |
> | `RouteOutcome.AMBIGUOUS` | `ROUTED_AMBIGUOUS` | `routed_ambiguous` | `more than one record matched, so nothing was performed` |
> | `RouteOutcome.AMBIGUOUS_TRUNCATED` | `ROUTED_AMBIGUOUS_TRUNCATED` | `routed_ambiguous_truncated` | `more records matched than could be shown, so nothing was performed` |
> | `RouteOutcome.NOT_FOUND` | `ROUTED_NOT_FOUND` | `routed_not_found` | `nothing matched, so nothing was performed` |
> | `RouteOutcome.UNRECORDED` | `ROUTED_UNRECORDED` | `routed_unrecorded` | `the decision could not be recorded, so nothing was performed` |
> | `RouteOutcome.FAILED` | `ROUTED_FAILED` | `routed_failed` | `the operation was attempted and failed` |
>
> The phrase column is the phrase `_outcome_of` and `_routed_outcome_of` return
> today, byte for byte, and §3 is what obliges a render site to produce it.

> **Normative.** No implementation, migration or later lane changes a member's
> serialised value once this ADR merges. A member added later takes a value of the
> same form — the member name lower-cased — and no member is given a second spelling,
> an alias or a numeric encoding.

**Why the values are fixed here rather than left to the lane.** A `StrEnum`
serialises its *value*, not its member name, and `EpisodicMemory` is wire-carried
(§8) as well as persisted. Two conforming implementations of the member list above
could therefore emit `step_executed` and `STEP_EXECUTED` for one fact, and every
record written under the loser would be undecodable — a compatibility break §8's
no-bump reasoning assumes cannot happen, on a field §8 makes the migration's
discriminator. `Disposition` and `RouteOutcome` already carry lower-cased values of
exactly this form, so the rule is the corpus's own and the table above simply writes
it down.

> **Normative.** `orchestration/engine.py`'s `_outcome_of` and `_routed_outcome_of`
> return members of this enum in place of prose, and each keeps its `assert_never`
> wildcard, so a member added to `Disposition` or to `RouteOutcome` without a member
> here fails the gate. No third mapping function is added and no member of either
> source vocabulary is added, removed or renamed by this decision.

**Why the two vocabularies stay distinct.** Three pairs are true synonyms and
eleven members are not: `NO_CAPABLE_TOOL` and `NOT_FOUND` are different facts about
different things, and five members exist on one side only. A normalised vocabulary
would therefore be a *lossy* projection dressed as a tidy one — and the loss falls
exactly where the value is, since the reason to type this at all (§10) is to count
what the assistant did. `AWAITING_CONFIRMATION` on a step and on a route are
different acts under different clauses (ADR-0170 §4 and ADR-0197 §10) and a measure
that could not tell them apart would be measuring nothing.

**Why one field and no validator.** ADR-0197 §1 makes the two mutually exclusive
structurally: a taken route drives no step, and a driven step means no route was
taken. A validator asserting it would be asserting a property of the pipeline from
inside a `core` type that cannot see the pipeline.

### 3. The render rule: the phrase where the enum is present, `outcome` where it is absent

> **Normative.** Every site that renders an episode's `outcome` into a model prompt
> renders **the phrase for `disposition` where the episode carries one**, and renders
> `outcome` as text where it does not. The three sites are
> `learning/observer.py`'s `_outcome_lines`, `planning/planner.py`'s `_render_record`
> and `orchestration/composing.py`'s `_render_record`. A record carrying a
> `disposition` has its `outcome` rendered into no model prompt by any of them.

> **Normative.** The phrase table lives at each render site and not in `core`. It is
> three tables of the same sixteen strings, and no implementation extracts them into a
> shared module, a `core` mapping, a method on the enum or a helper any two of the
> three import.

> **Normative.** No render site gains a byte budget, an elision rule or a truncation
> for this change, and none is owed one by it: what each renders is a constant of this
> system's own, of the length it has today.

**The fallback is what makes three populations render identically, and it is the
whole of the safety argument.**

- A **pre-change** episode carries a phrase in `outcome` and no `disposition`. It
  renders its phrase, exactly as it does today.
- A **post-change** episode carries the reply in `outcome` and a `disposition`. It
  renders the phrase for that disposition, which is the string a pre-change episode
  of the same shape carries — so the prompt is byte-identical and the reply reaches
  no model.
- A **benchmark-harness** episode carries the assistant's text in `outcome` and no
  `disposition`: `benchmarks/memory/ingest.py`'s `exchanges_of` fills
  `Exchange.outcome` from the assistant run and writes no disposition, because the
  harness does not run the engine's capture path. It renders that text, exactly as it
  does today, so the arm ADR-0162 §8 opened for `#1029`'s single-session-assistant
  questions is untouched and no harness result moves.

**The reply reaching no prompt is the point, not a side effect.** It is the same
rule as ADR-0197 §6 one layer over: a reader nobody chose is the accident to avoid.
Left alone, `_outcome_lines`' `f"       Assistant: {record.outcome}"` would make the
observer an accidental reader of model prose, through the one unescaped prompt
interpolation in the system (#672) — and the escaping fix is not sufficient there
either, because the render assumes one line per half and a composed reply is prose,
so ordinary non-adversarial replies would break the batch's structure. Whoever
first *reads* the reply owes both halves of that fix, plus the render budgets no
prompt has today.

**And it is what keeps this decision cheap to reverse.** Nothing user-visible
changes on merge: the episode's `outcome` reaches no adapter — `Belief` and
`BeliefSummary` project `content` and not `outcome`, and nothing under
`interfaces/` reads `TurnResult.memories` at all — so the reply is stored, rendered
nowhere, and available to the lane that decides to read it.

### 4. What this partially supersedes in ADR-0162 §8, and what of §8 is untouched

> **Normative.** ADR-0162 §8's first clause — *"The observation prompt states an
> episode's `outcome` where the episode carries one, beside the label, the recorded
> instant and the `content` that ADR-0077 §3 and ADR-0156 §2 already put there"* — is
> **partially superseded**. In its place: the observation prompt states the phrase for
> the episode's `disposition` where the episode records one, and its `outcome` where it
> does not, beside the same label, instant and `content`.

> **Normative.** ADR-0162 §8's four remaining clauses are untouched and bind
> unchanged: an episode is cited whole; what the assistant said independently supports
> a record of its own act; what the assistant said never supports a record adopting
> the proposition it asserted; and what the assistant said is never a licence to
> propose an `EpisodicMemory`.

**The act/proposition boundary is untouched, and the field naming inside it is
read rather than superseded.** §8's third clause says the act *"is a record of
something that happened, which the `outcome` field witnesses"*. After this decision
the act is witnessed by `disposition` and the *saying* by `outcome`; what the clause
obligates — which records the assistant's half may ground, and which it may not — is
unchanged, and no supersession is owed for a description of where a fact is stored.
The day a reader lane lets the production observer see the reply, §8's third and
fourth clauses are what govern what it may then propose, and they govern it as
ratified.

**And §8's own widening argument is not disturbed.** §8 admitted `outcome` into the
observation payload on ADR-0156 §2's ground, that it is *"a field of the very
`EpisodicMemory` records whose `content` §3 already sends"*. That ground is about
the record, not about the field's contents, so nothing here reopens ADR-0077 §3's
four refusals.

### 5. How the turn was captured: a record on the episode, carrying its modality

> **Normative.** `core/types.py` gains one frozen model, `Capture`, and one `StrEnum`,
> `Modality`, with two members — `TEXT`, valued `text`, and `SPEECH`, valued `speech`.
> `Capture` carries one field as this ADR ships it, `modality: Modality`, defaulting
> to `TEXT`. `EpisodicMemory` gains one field, `capture: Capture`, defaulting to a
> `Capture` with every field at its default. `Capture` is on `EpisodicMemory` alone
> and not on `MemoryBase`. §2's rule on serialised values binds `Modality` too: the
> two are fixed here and no later lane changes them.

> **Normative.** `modality` names how **the material the user supplied, whose
> rendering this episode carries**, reached this system — and nothing else. `SPEECH`
> says it reached this system as speech and that the text standing for it in the
> record is a derivation of that speech. `TEXT` is the default and says it did not:
> true of a typed turn, and true of an episode carrying no user material at all.

> **Normative.** `modality` says nothing about the assistant's own contributions to
> the record, and no consumer reads it as saying anything about them. The plan
> rationale rendered into `content` and the composed reply in `outcome` are text this
> system produced on every pass, whatever the utterance's modality, and this ADR
> records no modality for either.

> **Normative.** `Modality` is a vocabulary that is **added to and never renamed**. A
> later decision admitting a further input modality adds a member; no member of it is
> renamed, removed or given a second spelling, and no later ADR replaces this enum
> with a differently-named one for the same question.

> **Normative.** The value belongs to **the user material the episode renders**, not
> to the pass that performs the capture and not to the conversation. Every capture
> site falls in exactly one of the three cases below, and no implementation, setting
> or later lane adds a fourth without the ADR that decides it.

> **Normative.** **The episode renders the capturing pass's own user material** — a
> turn that pass produced, or the utterance a routed pass threads to the capture point
> (ADR-0197 §10). Capture writes `SPEECH` exactly where `Engine._capture` is given a
> `_SpokenCapture` — the passes of `AssistantEngine.converse_spoken` and no other,
> whether or not that pass routed — and `TEXT` otherwise. It asks nothing else and
> infers nothing: the capture path is told which operation it is running under and
> does not compute it.

> **Normative.** **The episode renders user material an earlier pass received** — the
> resolution of a parked step, which ADR-0074 §3 captures a second time and whose
> `content` renders that turn's goal statement and plan rationale. The value carried is
> that turn's own, retained with the parked turn and applied unchanged. No
> implementation re-evaluates, recomputes or defaults it at the second capture. This is
> ADR-0204 §2's fourth clause applied to a second field, for that clause's own reason.

> **Normative.** **The episode renders no user material at all.** Capture writes
> `TEXT`, and it is true of what the episode holds rather than a default it falls back
> on. Two passes are in this case: a resumption **recovered from durable state**, which
> has no turn to retain from, and the resolution of a **routed** park, whose episode
> carries neither a turn nor an utterance and renders the bare fact of the resumption
> alone. It is the same partition, at the same sites, that ADR-0204 §2's fifth clause
> already draws for the withholding stamp.

> **Normative.** `Capture` is the record the two further facts land in, and they are
> **not decided here**: which derivation produced the text, and whether and where the
> source material is retained. Each is an additive, defaulted field a later ADR adds
> to this record; adding one supersedes no clause of this ADR, and this ADR names
> neither field's type, spelling nor semantics.

> **Normative.** Nothing in this ADR retains source material, authorises retaining it,
> or is cited toward doing so. ADR-0200 §8's clause that no audio is written to any
> store, index, trace, audit trail, routing trail, outbox or log stands whole and is
> not touched by any sentence here.

**One modality on the record, and exactly one thing to read off it.** The
alternative — a modality per piece of text in the record — was weighed and declined.
An episode's `content` renders what the user asked, and the user's half is the one
part of the record whose modality is a fact about the world rather than about this
system; everything else in the record is text this system composed, and a field per
piece would be recording `TEXT` repeatedly to say so.

What one field buys is #1845's non-invariance argument, scoped to the half it is
actually about: a spoken turn's goal statement is a **transcript**, a lossy
derivation a model produced from audio, and without this field no reader can tell it
from words the user typed. A reader who does not know that cannot weigh the
statement — an odd word may be the user's or the transcriber's — and a lane that
later re-derives from a retained source needs to know which records are derivations
at all. That is the whole of what the field says. It licenses **no** inference about
the assistant's half: not about the modality of the composed reply, not about the
channel it was rendered to, and not about which operation the pass ran under. A
consumer that needs any of those is asking a question this field does not answer,
and the clause above is what forbids reading it as though it did.

**Why a record with one field rather than a field.** This is the owner's direction
of 2026-09-01 on #1845 and its reason survives the field count: a two-valued flag
would have to be **superseded** the day a second modality arrives, and it has
nowhere to put the two facts the "keep the source" direction needs. A record grows
by addition. A record with one field today has that property; a bare field does
not.

**Why the other two facts are not shipped as `None`-only slots.** Both were weighed
and both are declined on the same ground, which is the corpus's own standing test.

- *Which derivation produced the text* cannot be filled at all without a Protocol
  change. `SpeechToText.transcribe` returns a bare `EncodableText`: the model that
  produced the transcript is not in scope at the capture point, and putting it there
  is a change to `core/protocols.py`, which golden rule 5 and ADR-0015 §5 put behind
  its own ratified ADR. Shipping a field no producer may fill *and* no seam can fill
  would be choosing its type with no producer in hand — which is exactly what
  ADR-0073 §4 refuses, in the sentence ADR-0098 §5 quotes for the same purpose:
  whether a field is owed *"is a `core` decision for that lane — **with a producer in
  hand** — not one to guess here"*.
- *Whether the source is retained* has a known answer today and it is "no", by
  ADR-0200 §8, so the fact is recorded by the absence of any field for it. What a
  pointer into an archive would denote — the archive, its retention, its cascade
  under `forget`, `forget-conversation` and `delete_about`, and re-derivation as a
  supersession — is #1843's and milestone 21's ground on #1318, and choosing that
  field's shape here would pre-empt more of that design than the owner's direction
  asks for, not less.

**What this lifts, how far, and why it is a discharge rather than a
supersession.** ADR-0074 §11 defers *"Cross-device presence — which device is live in
a conversation"*, observing that *"nothing on a turn records where it came from"* and
that recording it *"would require a device identity, whose enrolment and revocation
the later arc owns"*. That rationale is exact for device identity and does not reach
modality: naming how the user material an episode renders reached this system needs
no enrolment, no revocation and no identity of any kind. §11 is a "what this ADR does not decide"
section and says of this bullet that it is *"Not foreclosed, and deliberately not
started"* and that *"adding it later is additive"*, so deciding it is what the bullet
invites. The deferral is **discharged in part**, not superseded: its device-identity
half stays open and unstarted, and so does §11's adjacent deferral of *who triggered*
an episode's retention.

**ADR-0200 §8 and ADR-0203 §4 are not superseded either, and the reason is
mechanical.** Each is a marked ADR, so under ADR-0089 §3 its marked clauses are the
whole of what it obligates. What each marks is a statement about **itself** — ADR-0200
§8: *"This ADR adds no field to `EpisodicMemory`, no field to `Provenance`, and no
record of the channel a turn arrived on"*; ADR-0203 §4: *"This ADR adds no field to
`EpisodicMemory`, adds no field to `Provenance`, records no channel on a turn"*. Both
sentences stay true of their own ADRs after this one, so neither is replaced. What
ADR-0200 §8 says beside its mark — that *"Milestone 21 is where the trigger and the
channel are the point, and §11 defers it there"* — is unmarked reasoning, which
ADR-0089 §3 reads to determine what a marked clause means and never as an obligation
of its own. Nothing in either ADR forbids this field, and ADR-0200 §8's clauses that
do bind a later lane — that no audio is retained anywhere, in either tier, by any
component — are honoured whole by §5 and restated there.

### 6. The record's own text, its origin mark, and what is not decided here

> **Normative.** Capture writes the captured episode's
> `Provenance.derived_from_external` exactly as it does today — it is not set, and
> takes its `False` default. This ADR adds no mark, threads no origin value to the
> capture point, and changes no value any component computes for that field.

> **Normative.** No lane implementing this ADR cites it as authority that the
> captured episode's origin is recorded, that the reply it now stores has been marked,
> or that ADR-0098 §5's recorded-origin gap is narrower than that section states.
> ADR-0098 §5's clause that *"No ADR, lane, or surface may state or imply that this
> posture detects external content embedded in text whose recorded origin is not
> external"* binds this ADR as it binds every other.

**The mark is owed, and it is owed its own decision.** #1845's argument is right
that the hole is live: the plan rationale is model prose this system's own
`_exchange_of` records into `content` truthfully and unmarked, which is ADR-0098
§5's own worked example — *"Every provenance field along that path is correct, and
**there is no field to read**"* — and §1 above puts a second piece of model prose
into the same record. It is also right that ADR-0098 §5's first deferral ground has
expired: the field exists, `Provenance.derived_from_external`, added by ADR-0106 §2,
so stamping it is no longer a `core` surface change. And a producer is now in hand,
which is ADR-0073 §4's standing test met.

**What it is not is prompt-neutral or permission-neutral, and that is why it is not
a rider on this one.** Two consequences were read from the tree rather than
inferred, and neither is named in #1845:

- `orchestration/composing.py`'s `_render_record` derives an episode's origin
  phrase from `rests_on_recorded_external_content`, so a stamped episode renders as
  *"resting on what a connected source reported"* where it renders *"recorded by this
  system"* today. That is a **prompt text change**, and it is the one thing §3's
  byte-identity test exists to detect. (`planning/planner.py`'s `_render_record`
  renders band and confidence only, and `learning/observer.py` renders neither, so
  the composing prompt is the only one that moves.)
- `Engine._run_turn` computes `SelectionOrigin.over(turn.memories)` over a supply
  whose first group is the conversation's own recent turns. A stamped episode
  entering that group therefore carries `planned_with_external_content` to the egress
  seam on **later** turns — and `core/protocols.py`'s `ActionPolicy.decide` is
  ratified to return *"no ``ALLOW`` at all on a request whose ``egress_binding``
  carries ``planned_with_external_content``"* (ADR-0181 §5's third clause). So the
  stamp removes the automatic allow for every egress call of a conversation that has
  once held an external record, until those episodes leave the tail.

Both may well be the right answers — the second is arguably ADR-0181 §4's
anti-laundering rule working as designed, since a value that said `False` there
would be saying something untrue. Neither is a memory-record question, both reach
subsystems this lane does not touch, and each deserves the argument and the review a
decision of its own gets. §13 defers the mark with its trigger; #1845's coupling
note stands and is worth repeating, because deferring it removes the one downstream
gate and leaves the reader lane's escaping fix as the only control on an injected
reply.

**Observer propagation stays out either way**, and today that costs nothing to
state: `learning/observer.py` and `orchestration/observation.py` compute no
disjunction of this field over their batch, so the observer does not propagate it
and no clause here changes that. `orchestration/consolidation.py` does compute one,
over the records it was supplied, and that is ADR-0106 §3 applied where it already
binds.

### 7. Tier at capture: the reliance, stated rather than assumed

> **Normative.** Capture stores the reply without inspecting it for a Tier 0 value,
> and no implementation adds such an inspection on this path. The reliance is that
> the composing stage is supplied nothing holding a Tier 0 value, which ADR-0004 §3
> secures by residency: Tier 0 secrets live in the OS keyring, are read through
> `SecretStore` by `models/` and `tools/` alone, and are in no record, facet, plan or
> step account the composing stage is given.

> **Normative.** That reliance is a **test the implementing lane owes**, not an
> assumption it may leave implicit. §11 states it.

> **Normative.** Routing capture through `MemoryWriter.ingest` is not the remedy and
> is not adopted. That refusal keys on a producer-declared `proposal.sensitivity`
> and records carry no tier at all, so it would refuse nothing this stores. No lane
> cites this ADR as a reason to route capture through the writer, and none cites the
> writer as covering what §7 relies on.

**ADR-0199 §3's first clause is cited for the floor and for nothing else.** That
clause — *"No reply and no delivery, on a channel of any audience, carries a Tier 0
value or any span of one (ADR-0004 §1). This is a floor rather than a posture"* — is
a rule about an output channel, and this decision stores what that channel carried.
Its own prose concedes that *"the clause forbids a case that is currently
unreachable"*, so it is quoted as the floor that makes the stored value's class
knowable and not as a mechanism that checks it. §3's other clauses, which place
classes as speakable or withheld on an unbounded channel, are not engaged by a store
write and are not cited here.

### 8. Migration is self-clearing, and `PROTOCOL_VERSION` does not move

> **Normative.** `outcome` keeps its type, `EncodableText | None`, and its
> `max_length`, its validators and its nullability are unchanged. Both new fields are
> additive with defaults on models that do not set `extra="forbid"`, so every record
> already in a store deserialises and no migration, backfill, column or index is
> required or permitted by this decision.

> **Normative.** The **absence** of `disposition` is the discriminator between a
> record written before this decision and one written after it, and no other
> discriminator is introduced. No implementation infers the population from the
> record's text, its length, its instant or its store.

> **Normative.** `PROTOCOL_VERSION` does not move for this change.

**The version rule is applied rather than asserted past, and on the right premise.**
ADR-0124 §9's test is that the version is bumped by any change after which a frame a
conforming peer at the new version may send *"would be refused by a conforming peer
at the old version, or would be accepted by it with a different meaning"*.
`EpisodicMemory` **is** wire-carried — `TurnResult.memories` is
`tuple[MemoryRecord, ...]` inside `TurnOutcome.turn`, which is the ground
`wire/envelope.py` gives for the bump to 23 — so the test has a subject, and the
answer comes from two rulings on this same envelope:

- **The two added members** are ADR-0213 §11's case exactly: additive, defaulted, on
  models that do not set `extra="forbid"`, so an older peer decoding a newer hub's
  record ignores a member it does not know, and the direction that would break does
  not exist — no `AssistantEngine` method takes a `MemoryRecord` as an argument, and
  `wire.surface.METHODS` is derived from that Protocol. No member is *removed*, which
  is what separates this from ADR-0217 §9's bump, where a removed member's default is
  read.
- **The changed contents of `outcome`** are ADR-0210 §8's case: *"What changes is a
  value the hub **computes**"*, on a field whose shape, encoding and nullability are
  unmoved, with the precedent chain running back to ADR-0203 §5. And the meaning an
  older peer could take differently is one no peer takes at all: nothing under
  `interfaces/` reads `TurnResult.memories`, and no client holds a `MemoryStore`.

**Absence as the discriminator is what makes the migration self-clearing.**
`episode_retention` is finite at thirty days by default and enforced at read time,
so after one window no record carrying the old meaning is live. The named edge is
`episode_retention = none`, which makes the transient permanent — and the
discriminator still works, because it is a field's presence and not a date.

### 9. What this decides about #1235, and what it does not

> **Normative.** This ADR decides what `outcome` carries on an episode a turn
> captures. It neither opens nor forecloses #1235's assistant-opening utterance, and
> no lane cites it as having decided either way. Whether an assistant-only utterance
> is an episode at all, what its `content` would be, and whether `outcome` is its
> carrier are #1235's, and #1235 is answered against its own text and not against
> this one.

**Stated because it would otherwise be re-litigated against the merged text.**
#1235 names `outcome` as the carrier for "the assistant said this", and this
decision names what `outcome` carries. The overlap is real and the conclusion does
not follow: this ADR rules over episodes a *turn* captures, which have a user half
by construction, and says nothing about a record that has none.

### 10. The typed disposition as a consequence, not as a motivation

The reason to store the reply is #1842's, and it stands alone. But the enum §2 adds
is not only a rendering detail, and stating what it buys keeps a later lane from
treating it as one.

Today "how often is a plan step denied by policy?" and "how often does a routed
lookup find nothing?" are questions answerable only by matching prose against
sixteen constants. Afterwards they are a filter over a closed vocabulary this
system owns. #1564's uninstrumented measures — accepted versus dismissed,
overrides — are counts over exactly this vocabulary, and #1842's fifth requirement
needs a typed act for a `FeedbackEvent` to point at, which this makes
representable without making it (that is a Protocol-surface change and its own
ADR). And `assert_never` over the type means a member added to `Disposition` or to
`RouteOutcome` fails the gate at every render site until each has answered it, which
is the property the prose form gave for one site and now gives for three.

### 11. The representative-input tests this decision owes

These are what the implementing lanes must make a test say, not a file layout. Each
names an input and the outcome it fixes.

1. **The reply round-trips whole.** A turn whose composed reply is a multi-line
   string of a few hundred characters captures an episode whose `outcome` is that
   string, byte for byte, through the `MemoryStore` conformance suite so every
   implementation persists it.
2. **The five no-reply paths each capture `outcome=None`**: a step parked for
   confirmation, a routed park, a resume driven from a recovered park, a classified
   composition failure, and a stream that published nothing.
3. **A cut stream stores what was published**, on both of its shapes: a ceiling stop,
   and a mid-stream `ModelError` after at least one chunk. The stored text equals the
   text of the chunks the stage emitted, and `TurnOutcome.reply_degraded` is `True`.
4. **A distinctive span in a captured reply appears in no subsequent prompt.** Capture
   a reply containing a span nothing else in the fixture carries; run a further turn
   of the same conversation and an observation pass over that episode; assert the span
   occurs in no prompt the observer, the planner or the composer assembled. This is
   the test a reader lane must consciously delete.
5. **The rendered prompt is byte-identical across the change, on a record with the
   enum.** For each of the sixteen members, at each of the three render sites, the
   rendered text equals what the same site renders for a record carrying that member's
   phrase in `outcome` and no `disposition`.
6. **Legacy renders and observes.** A record carrying a phrase in `outcome` and no
   `disposition` renders at all three sites and completes an observation pass without
   error, and its rendered text is unchanged.
7. **A harness row renders its assistant text.** A record built as
   `benchmarks/memory/ingest.py`'s `exchanges_of` builds one — assistant text in
   `outcome`, no `disposition` — renders that text at all three sites.
8. **Every enum value is pinned.** Each of `ExchangeDisposition`'s sixteen members
   and each of `Modality`'s two serialises to the exact string §2 and §5 name, and a
   record round-trips through serialisation carrying the same member back — asserted
   over the whole membership, so a member added later without a value of the stated
   form fails rather than passing silently.
9. **A record constructed with neither new field** carries `disposition` of `None`
   and a `capture` whose `modality` is `TEXT`, and a serialised record written before
   the fields land decodes to the same.
10. **A spoken turn's episode carries `SPEECH` and the spoken reply**, and so does a
    pass of `converse_spoken` that routed; a turn of `converse` and one of
    `converse_streaming` each carry `TEXT`.
11. **The three resumption shapes are each pinned.** The resolution of a **step**
    park of a spoken turn carries `SPEECH`, retained from the parked turn rather than
    recomputed by the resuming pass; the resolution of a **routed** park carries
    `TEXT`, including where the pass that parked it was spoken; and a resumption
    **recovered from durable state** carries `TEXT`. Together they pin §5's partition,
    and the routed arm is the one that separates "the pass was spoken" from "the
    episode renders spoken material".
12. **A routed pass's episode carries a routed member and its reply.** The
    `disposition` is the `ROUTED_*` member for the route's outcome, the `outcome` is
    the composed reply, and the episode still carries no part of the routed account
    (ADR-0197 §10) — no listing, no display subject, no scalar argument, no candidate.
13. **The Tier 0 reliance is asserted at the seam it rests on**: the values the
    composing stage is supplied on a turn — records, facets, plan and step account —
    are enumerated in a test that fails if a future field admits a `SecretStore` value
    into any of them.
14. **No log carries the reply.** The capture and observation paths emit no log event
    whose payload contains the captured reply's text (ADR-0004 §5 names *"message
    bodies"* a redaction target).
15. **`derived_from_external` is unmoved.** A captured episode's provenance carries
    `False`, pinning §6 so a later lane changes it deliberately.

### 12. What the implementing lanes owe

The implementation is three lanes, each briefed after the one before it merges
(ADR-0015 §5, golden rule 5). The cut is ADR-0137 §1's: the new machinery is one
`core` addition, and everything after it is adaptation.

**Lane C — `core/types.py` alone.**

1. `ExchangeDisposition` with §2's sixteen members and their values, documented in
   place with what each denotes and which source vocabulary it mirrors.
2. `Modality` with `TEXT` and `SPEECH` and the values §5 fixes, and `Capture` as a
   frozen model carrying `modality` alone. **The docstring states §5's meaning by
   quoting §5 rather than paraphrasing it** — three lanes restating one rule is how
   the two drift apart — so it says that the value belongs to the user material
   *whose rendering the episode carries*, which on the resolution of a parked step is
   the parked turn's and not the resuming pass's; that it says nothing about the plan
   rationale in `content` or the composed reply in `outcome`, which are text this
   system produced whatever the utterance was; that §5 is where the three capture
   cases are decided and a producer reads them there; and that `Capture` is the record
   §5's two deferred facts land in.
3. `EpisodicMemory.disposition: ExchangeDisposition | None = None` and
   `EpisodicMemory.capture: Capture`, defaulted as §5 states.
4. A rewritten description on `EpisodicMemory.outcome` saying what it now carries,
   that a record carrying a `disposition` carries the reply there, and that a record
   carrying none carries a phrase or a harness-supplied text. This is the prose edit
   ADR-0210 §8 obliges for the same reason: a `core` type documenting a rule the
   system no longer follows is worse than the change it hides.
5. The canonical fakes and record builders in `ai_assistant.testing` extended to
   carry both fields, and the `MemoryStore` conformance suite pinning their
   round-trip so no implementation silently drops them. **`core/protocols.py` is not
   edited, no Protocol is added and no member is added to one, so no triad is owed.**
6. Tests 8 and 9 of §11.

**Lane D — the three render sites.** After C merges.

1. `learning/observer.py`'s `_outcome_lines`, `planning/planner.py`'s
   `_render_record` and `orchestration/composing.py`'s `_render_record` each render
   §2's phrase for `disposition` where one is present and `outcome` where it is
   absent, from a phrase table written out at that site.
2. Each table is total over `ExchangeDisposition` with an `assert_never` wildcard.
3. Tests 5, 6 and 7 of §11. Adaptation across three subsystems and no new machinery,
   so one lane (ADR-0137 §1).

**Lane E — the capture flip.** After D merges.

1. `orchestration/engine.py`: `_outcome_of` and `_routed_outcome_of` return
   `ExchangeDisposition` members; `_capture` writes the reply into `outcome` and the
   member into `disposition`, and threads the modality from the `_SpokenCapture` it
   already receives.
2. §5's three cases at the sites that realise them: `_run_turn` and `_finish_route`
   stamp from their own pass's `_SpokenCapture`; the parked turn **retains its
   modality** and `_capture_resumption` passes that retained value rather than the
   resuming pass's — the same shape, at the same site, as the `supplied_withheld` that
   park already retains (ADR-0204 §2's fourth clause); and
   `_compose_and_capture_routed`, together with a park recovered from durable state,
   passes `TEXT`, exactly where each already passes `supplied_withheld=False`.
3. `orchestration/conversations.py`: `_episode` stamps the two new fields and every
   other field exactly as ADR-0074 §4 and ADR-0217 §1 fix them.
4. Tests 1, 2, 3, 4, 10, 11, 12, 13, 14 and 15 of §11. The benchmark harness is
   untouched.

> **Normative.** A lane implementing the above and also stamping an origin mark, or
> reading the reply into any prompt, or adding a render budget, or touching
> `benchmarks/`, has exceeded this decision.

### 13. Deferred, by name, each with what fires it

- **The origin mark on the captured episode** (§6). Its own ADR and its own lane.
  Fired by whoever picks it up; what that decision owes is the composing prompt's
  origin phrase changing on a stamped record, and ADR-0181 §5's third clause removing
  the automatic `ALLOW` for the egress calls of later turns. Tracked as its own issue.
- **Every reader of the stored reply**: the production observer seeing it, retrieval
  by its text, #1314's second-turn reference-back, and the render budgets and elision
  rules none of the three prompts has today. Fired by the first lane that wants one,
  and each owes #672's escaping fix *and* newline normalisation before it renders a
  reply into the observer's line-oriented batch.
- **The source archive and what a pointer into it denotes** — its retention, its
  cascade under `forget`, `forget-conversation` and `delete_about`, and re-derivation
  as a supersession. #1843 and milestone 21 of #1318. Fired by that decision, and §5
  is the field's landing place.
- **Which derivation produced an episode's text.** Blocked on a `core/protocols.py`
  change: `SpeechToText.transcribe` returns a bare `EncodableText`. Fired by the ADR
  that decides that Protocol change.
- **A `FeedbackEvent` naming a typed act** (#1842's fifth requirement). A promoted
  Protocol surface change and its own ADR; §10 makes it representable and does not
  make it.
- **#1235's assistant-opening utterance** (§9), and **ADR-0197 §12's two-turn test**,
  which is deferred with the render because its subject is a prompt.

### 14. Scope

> **Normative.** This ADR adds three names to `core/types.py` —
> `ExchangeDisposition`, `Modality` and `Capture` — and two fields to
> `EpisodicMemory`. It changes nothing else in `core`. `core/protocols.py` is
> untouched: no Protocol, no member on one, no changed signature. It adds no
> `Settings` field, no member of the promoted `AssistantEngine` surface, no wire
> operation, no tool and no `RoutableOperation` member.

> **Normative.** No read returning records is filtered on `disposition` or on
> `capture` by this ADR. `MemoryStore.search`, `list_beliefs`, `get`, `get_many`,
> `export` and `walk_records` gain no argument for either, and no surface, consumer or
> later lane adds one without the ADR that decides it.

> **Normative.** Nothing here authorises egress, relaxes a permission floor, widens a
> grant, or is cited toward a designation, a registration or a destination. Nothing
> here places a class as speakable on any channel or unplaces one: ADR-0199 §3's
> placements, ADR-0203 §1's subtraction, ADR-0210 §1's evaluation set and ADR-0217 §2's
> read rule are each untouched, and an episode's placement is stamped exactly as
> ADR-0217 §3's derivation fixes it.

> **Normative.** This decision changes no retention. `episode_retention` is unmoved,
> the sweep is unmoved, and `ADR-0074 §7`'s horizon is what bounds the reply's life as
> it bounds the rest of the episode's.

**ADR-0004 §7's minimisation, discharged in a paragraph because that is what it
asks for.** #1221 raises it. Retention is already paid: `ConversationLifecycle`'s
`_episode` stamps `expires_at` from `episode_retention`, finite by default and
enforced at read time, and ADR-0074 §7 wrote the justification for this content
class — *"the tension is not resolved by capturing less; it is resolved by episodes
being a different kind of thing with a shorter life"*. The user-facing rights exist:
`assistant beliefs --kind episodic`, `assistant forget`, `assistant
forget-conversation`, each mirrored on the gateway. §7 itself asks for no mechanism
— two prose bullets predating the `**Normative.**` convention, read narrowly by
ADR-0017 §9, ADR-0016 and ADR-0202 — and no lane has ever added machinery because of
it. The one genuinely new limb is egress rather than storage, since ADR-0162 §8 puts
`outcome` into the observation prompt; §3 answers it by never putting the reply
there, which is a stronger answer than a budget.

## Consequences

- **The store finally records what the assistant did and said.** Every episode a
  turn captures carries the user's half in `content`, the assistant's half in
  `outcome`, and a typed statement of what became of the pass. #1221 and #1314 are
  closed as to storage; #1314's motivating experience waits for a reader.
- **Nothing user-visible changes on merge**, and that is the point rather than a
  disappointment: the reply is stored, no prompt renders it, and no adapter reads
  `outcome`. Whoever first reads it does so deliberately, against a test written to
  fail when they do.
- **Three prompts stay byte-identical**, and the property is mechanical rather than
  hoped for: the phrase table reproduces today's strings, the enum-absent fallback
  covers the pre-change and harness populations, and §11's test asserts it member by
  member and site by site.
- **A new member of `Disposition` or `RouteOutcome` now costs four answers** —
  `ExchangeDisposition` and the three phrase tables — where it cost two. That is the
  price of the totality, and `assert_never` collects it at the gate rather than in
  production.
- **The disposition becomes countable**, which is what #1564's measures and #1842's
  fifth requirement each need and neither had.
- **The episode records how the user's half reached the system**, so a transcript is
  distinguishable from typed words — which is what makes the non-invariance of a
  spoken record coherent rather than merely asserted, and what a later re-derivation
  would need to find its subjects.
- **The origin gap stays open and is now stated in two places rather than one.** §6
  declines the mark and says why; the reader lane's escaping fix is, as #1845 notes,
  the only control on an injected reply until the mark's own decision lands.
- **What would trigger revisiting this.** A reader that needs the reply at a
  fidelity `outcome` cannot carry; a measurement showing the phrase tables have
  drifted between the three sites; or an archive decision that wants `Capture` shaped
  differently, which §5 makes an addition rather than a supersession.

## Alternatives considered

- **Store a prefix of the reply.** Rejected on ADR-0170 §8's own ground: the corpus
  refuses an oversized answer at the wire rather than clipping it, and an assertion
  whose meaning depends on its ending is not half-storable. #1834 disposes of the
  distilled variant.
- **Store the reply in `content`.** Rejected, and this is the requirement that
  chooses the slot. `content` is the embedded field and retrieval is content-addressed
  across the whole retention window, so an actor who influences what the assistant
  says would choose which of the user's future questions retrieve their text. Only
  `outcome` is non-embedded today, so the property holds by construction rather than
  by a rule a later lane must remember. The reply stays reachable by position, by a
  belief's citation, and by the *question's* similarity to `content` — three keys,
  none of them the reply's own text.
- **A second store for the assistant's half.** Rejected on ADR-0074 §3's ground: two
  retention rules and two deletion surfaces over one exchange, with no transaction
  between them, and ADR-0072 §3's citation referent broken on the day something cited
  one.
- **Normalise the two vocabularies into one smaller enum.** Rejected in §2: eleven of
  the sixteen members have no counterpart, and the three synonym pairs denote acts
  under different clauses.
- **Put the phrase table in `core`.** Rejected on golden rule 1 and on the owner's
  direction: `learning`, `planning` and `orchestration` would share an implementation
  across a boundary they may not import across, and the shared thing would be prose
  rather than a contract. Three tables of sixteen strings is the cheap, legible form,
  and §11's test is what keeps them equal.
- **Ship `Capture` with `derived_by` and `source` as `None`-only slots.** Weighed,
  and declined in §5 on ADR-0073 §4's standing test: neither has a producer in hand,
  one is blocked behind a Protocol change, and the record shape — which is what the
  owner's direction is *for* — already lets both land additively later.
- **A `spoken | typed` boolean or two-member flag on `Provenance`.** Rejected: it
  would have to be superseded rather than extended by the second modality, it belongs
  to the record rather than to the warrant, and ADR-0217 §1 has just finished moving a
  field off `Provenance` for the neighbouring reason.
- **Thread the origin mark in this ADR.** Weighed at length and declined in §6, on
  two consequences read from the tree: it changes the composing prompt's origin
  phrase, which is exactly what §3's byte-identity property exists to catch, and it
  removes the automatic `ALLOW` for later turns' egress calls under ADR-0181 §5. Both
  reach subsystems this decision does not touch.
- **Defer the whole thing until a reader exists.** Rejected: the reader lane's cost
  is the escaping fix, the newline normalisation and the render budgets, and none of
  those becomes cheaper by having no data to read. Storing first is what lets that
  lane be scoped against real records.

## What this records against earlier ADRs, under ADR-0082 §1

- **ADR-0074 §3** — partially superseded as to what `outcome` carries. Its sentence
  *"`EpisodicMemory` carries an `outcome`, which is a property of a completed
  exchange"* stands as to the property; what the field holds is §1's. §4 is not
  superseded: it rules `content`, `importance`, `participants`, `validity` and the
  provenance stamps, and says nothing normative about `outcome`.
- **ADR-0074 §11** — **discharged in part, not superseded** (§5). Its cross-device
  bullet defers recording where a turn came from as *"Not foreclosed, and deliberately
  not started"*, and §5 decides the modality half of it. Its device-identity half, its
  retention-trigger bullet and every other item of §11 stand, and no `Status` record is
  made on that ground.
- **ADR-0200 §8 and ADR-0203 §4** — **not superseded** (§5). Each marks a statement
  about its own ADR — *"This ADR adds no field to `EpisodicMemory`…"* — which stays
  true of it, and under ADR-0089 §3 the marked clauses are the whole of what a marked
  ADR obligates, so ADR-0200 §8's unmarked placement of the question at milestone 21
  binds nothing. ADR-0200 §8's no-audio-retention clauses and ADR-0203 §4's clauses
  about what a spoken capture carries and about #1703's residual stand whole and are
  restated in §5.
- **ADR-0162 §8** — its **first** clause partially superseded (§4). Its other four
  clauses stand.
- **ADR-0162 §1 and §2** — not superseded. §2's classifier reaches *"an episode whose
  content is what the user said to the assistant"*, and `content` is unchanged by this
  decision, so an episode carrying a reply in `outcome` is still an episode of §1's
  class. This is a widening within §1's own episodes and not a second class of
  episode, so §2's third clause — that a producer implementing §1 is never handed one
  outside it — needs no carrier and gets none.
- **ADR-0204 §2** — not superseded, and cited clause by clause. Its *"unchanged, on
  every channel"* attaches to the episode's `content`, which this decision does not
  touch; its *"No other field of the episode changes"* states what **that** ADR did and
  is not a prohibition on a later one. Its second clause is already partially
  superseded by ADR-0210 and its stamp already relocated by ADR-0217 §1, and neither
  is disturbed here.
- **ADR-0197 §10** — not superseded and not distinguished. It reserved this ground in
  terms and this decision spends the reservation. Its own clauses bind unchanged: the
  captured episode still carries no part of the routed account, which §1 leaves true
  because ADR-0197 §6 gives the composing stage two enum values and nothing else, so a
  routed reply cannot contain what §6 withholds.
- **ADR-0170 §8 and §9** — not superseded. §8's no-silent-truncation clause is applied
  in §1; §9's deferral is discharged by being decided in the track it named.
- **ADR-0106 §2 and §3** — not superseded and not extended. §6 declines the stamp, so
  no producer beyond those §3 already reaches is brought under it.
- **ADR-0098 §5** — not discharged, not narrowed, and cited only for the gap it
  states (§6).
- **ADR-0199 §3** — its **first** clause cited, for the Tier 0 floor and nothing else
  (§7). Nothing here places or unplaces a class.
- **ADR-0213 §11 and ADR-0210 §8** — applied, not superseded: they are the two
  rulings §8 reasons from.
- **ADR-0015 §5 and golden rule 5** — this ADR is a contract-surface decision. It
  ships alone, is reviewed under both the adversarial and the architecture lens while
  `Proposed`, and nothing implements against it until it merges. Its status was
  flipped only once both required reviews returned clean on one tree; `CONTRIBUTING.md`
  → "Finishing an ADR PR" is the sequence, and this ADR takes it rather than
  re-arguing it.
