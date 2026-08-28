# 207. A parked spoken turn says one fixed sentence naming the screen, and nothing else fills the silence

- Status: Proposed
- Date: 2026-08-28
- **Partially supersedes:**
  [ADR-0200](0200-a-spoken-turn-is-one-operation-on-the-promoted-surface-and-speech-is-two-seams-beside-the-model-provider.md)
  — §4's park clause ("`spoken` is `None` wherever `outcome.reply` is `None`: a
  park, a recovered resume, and a composition failure each leave nothing to say…
  On those shapes `spoken_degraded` is `False`") and the two clauses it controls:
  "`spoken` is the rendering of `outcome.reply` and of nothing else", and
  `spoken_degraded`'s "**exactly when** an answer existed" predicate. Each is
  replaced **only** as it reaches a `converse_spoken` pass whose outcome is a live
  confirmation park. §3 below states the whole of the difference and forbids a
  third. The recovered resume and the composition failure keep their silence word
  for word, `SpokenTurn`'s members stand as ADR-0205 §1 left them, the four
  degradation cases stand,
  both payload measurements stand, and §7 in full is untouched — §9 classifies
  every record and every ADR against which none is owed.
- **The record on ADR-0200 is made in this change, while this ADR stands
  `Proposed`, and its pair goes on the `Status` line.** Both halves are settled
  corpus rulings, both were misread in review of this very PR, and both are stated
  here rather than left to be re-derived. **Timing:** ADR-0082 §7 fixes the
  condition and names the opposite reading — "**#458 — the recurring misreading of
  ADR-0070 §1's 'a supersession that has landed' clause.** Not a governance gap but
  a reviewer failure mode, so this ADR states the condition rather than re-deciding
  it: §1's condition is that the superseding ADR **exists**, not that it is
  ratified — the hazard §1 names is a `Status` line pointing at nothing, and an
  **atomic pair** makes that unreachable." This PR is that atomic pair. **Place:**
  ADR-0070 §4 rules that "**independent partial supersessions accumulate on the one
  line**" and that "adding the second pair is a §1 Status edit (recording a
  supersession that landed) and it does **not** drop the first". ADR-0082 §2's
  note-only rule governs an *amendment qualifier* on a leading-token line, and
  ADR-0082 §7 says as much outright: "the accumulation rule for multiple partial
  supersessions is §4's and is untouched". ADR-0165's header records that *its*
  records waited for ratification; that bullet says why one lane waited, on the
  precedent of two others, and ADR-0165 §7 leaves "ADR-0070 §1's rules on what an
  in-place header edit may be" untouched — it is a lane's choice and not the
  condition.
- **This is a contract change, and the brief that commissioned it said otherwise.**
  `SpokenTurn`'s `model_validator` in `core/types.py` refuses a rendering beside an
  outcome with no reply, so implementing this decision changes `core/types.py`, and
  it changes it in a way ADR-0124 §9's second limb reaches. The type gains no
  member, no field and no encoding; what widens is which of its four-member shapes
  are admitted. It owes **both** lenses (`CONTRIBUTING.md` → "Stop when the required
  reviews are green"), and it merges and is ratified before anything implements
  against it (ADR-0015 §5, golden rule 5). §6 states the surface and §7 the bump.
- **Durability clause.** Every quotation below — from an ADR, from `core/types.py`,
  from `orchestration/engine.py`, from `wire/`, from `core/config.py`, or from an
  issue — is of its text as it stood at this ADR's base, `cb43d0ec`, and not of its
  text on any later day. **ADR-0204, ADR-0205 and ADR-0206 merged into that base
  while this ADR was under review**, and each is quoted as it stands there; §9
  states what each moves and what none of them moves.
  Where a later ADR changes one of the ADRs cited, this ADR is read against the text
  quoted here and that ADR's own record says what moved. This is ADR-0143's clause,
  taken for its reason.

## Context

### Where this comes from

`track:voice` (#1318) milestone 19 is push-to-talk in a browser: the owner holds a
button, asks aloud, and hears an answer drawn from accumulated memory. ADR-0199
decides what may be said on such a channel and ADR-0200 decides the mechanism —
one operation, `converse_spoken`, returning one `SpokenTurn`.

#1699 measured that operation from the laptop against the deployed hub, with
utterances manufactured by a real synthesizer and the answers transcribed back.
Two utterances, and the second is the one this ADR exists for:

| utterance | outcome | `reply` | `spoken` |
| --- | --- | --- | --- |
| "What is my name?" | composed | "Your name is Leonardo." | yes |
| "What do I take in my coffee?" | `AWAITING_CONFIRMATION` | none | none, `spoken_degraded` `False` |

The second result is **exactly as ratified**. ADR-0200 §4 rules that "`spoken` is
`None` wherever `outcome.reply` is `None`: a park, a recovered resume, and a
composition failure each leave nothing to say, and nothing is invented to fill the
silence." The planner reached for a medium-risk tool, the policy wanted a human
answer, the step parked, no answer was composed, and so nothing was said.

What the owner experiences is the part the clause could not have anticipated:
**hold, ask, release, hear nothing** — and a confirmation card appears on a screen
they were not looking at, because the reason they were speaking is that they were
not looking at a screen. Silence on a push-to-talk surface is indistinguishable
from a hub that is down, a button that did not register, or a recording that
carried no words, and ADR-0199 §5 already writes that observation down for a
different case: "When the owner asks a question aloud, silence is
indistinguishable from a system that failed."

The owner ruled on #1699 on 2026-08-28: **yes** — a spoken turn that parks on a
confirmation says a fixed, content-free sentence in the deflection's shape,
instead of silence. Product semantics are settled by that ruling; what is left,
and what this ADR decides, is which clauses move, what exactly is said, what
carries it, and what the change costs on the wire.

### What the tree does today, read rather than remembered

Each of these was read at `df06a763`, the base this ADR was drafted against, and
re-checked at `cb43d0ec`, the base it now stands on and the one its durability
clause names. Nothing here moved between the two: ADR-0204, ADR-0205 and ADR-0206
merged in that range and `git diff df06a763 cb43d0ec` touches no line of
`core/types.py`, `orchestration/engine.py`, `core/config.py` or `wire/` — the four
this section quotes. Their *decisions* do reach this one, and §5 and §9 say where.

- **The silence is produced in one place.** `Engine._spoken_rendering` opens
  `if reply is None: return None, False`, under a docstring that states the ruling
  it implements: "**Nothing to say is not a degradation.** A park, a recovered
  resume and a composition failure each leave `reply` `None`, and nothing is
  invented to fill the silence."
- **`SpokenTurn`'s validator enforces it from the other side, in `core`.**
  `core/types.py`'s `_shapes_are_the_ones_adr_0200_admits` computes
  `answered = self.outcome is not None and self.outcome.reply is not None` and
  raises on `not answered and self.spoken is not None` — "spoken is the rendering
  of the outcome's reply, so it is None wherever there is no reply to render
  (ADR-0200 §4)" — and again on `not answered and self.spoken_degraded`. **A
  rendering on a park is not merely absent today; it is refused at construction.**
  This is the fact the commissioning brief did not have, and it is what makes this
  decision a contract change rather than a conduct change inside `orchestration`.
- **There are two park shapes on this operation, not one.** #1699 measured the
  **step** park: `Disposition.AWAITING_CONFIRMATION`, whose `StepOutcome.confirmation`
  is "present **iff**" that disposition, and whose step is "durably
  `AWAITING_APPROVAL`; `AssistantEngine.resume` continues it". `converse_spoken`
  also drives ADR-0197's routing stage — `_converse_spoken` passes
  `compose_routed=self._composed_routed_spoken` — and a confirm-owed route parks
  too: `_routed_pass` reaches `RouteOutcome.AWAITING_CONFIRMATION` and then calls
  `_finish_route` with `compose=None`, whose docstring reads "`compose` is `None`
  on a routed park, which owes no answer: the composing stage is not reached,
  originates no model call, and `reply_degraded` stays `False`." Both shapes leave
  `outcome.reply` `None`, both mint a confirmation the user must answer on a
  screen, and both are silent aloud today for the same reason.
- **The third silence is a composition failure**, where `reply` is `None` and
  `reply_degraded` is `True`. The fourth shape ADR-0200 §4's park clause names —
  a **recovered** resume — is not reachable through this operation at all: a
  `SpokenTurn` is produced only by `converse_spoken`, which resumes nothing, and
  `resume` is a separate member of the promoted surface returning a `TurnOutcome`.
  The limb is not wrong; it has no subject here, and this ADR leaves it exactly
  as it stands for the operation that does have one.
- **The card carries text nothing may speak.** A step park's `Confirmation` is
  assembled from "the **recorded** `CONFIRM` the runner already read back" — the
  tool declaration and the policy's `reason`. A routed park's
  `OperationConfirmation` carries the operation and "the resolved subject as a
  typed value". Each of those is content about what the user asked; none of it is
  content this decision proposes to say aloud.
- **A fixed, project-authored sentence beside a card is the corpus's own pattern,
  not a new one.** ADR-0197 §7's routed card "carries no model-written text… every
  word the user reads around them is the adapter's own, selected by the enum
  member. No free text the router produced — the query included — reaches it."
- **Three sibling decisions of this batch merged while this ADR was under review**,
  and each was read against the tree rather than against its brief. **ADR-0205**
  gives `SpokenTurn` a fifth member, `episode_id`, gives `converse_spoken` a fifth
  argument, and rules that capture writes an `UNKNOWN` delivery state on this
  operation "including where the answer was parked". **ADR-0204** adds
  `Provenance.supplied_withheld_content` and a supply-site test for an unbounded
  channel. **ADR-0206** decides the delivery direction — a notification spoken where
  the poll asked, a withheld one arriving unspoken. §5 states what each means for a
  park and §9 classifies this ADR against all three.
- **`SpokenTurn` is wire-carried and the client reconstructs it.**
  `wire/client.py`'s `converse_spoken` is annotated `-> SpokenTurn`, and a result
  payload "takes the shape of the method's own declared return annotation"
  (ADR-0085 §10), so the validator quoted above runs on the client's side of the
  hop as well as the hub's. `PROTOCOL_VERSION` is `18` at this base.

### What is not in dispute, and is used as given

- **ADR-0199 §2** — a class is decided from recorded origin, "never by inspecting
  the content for what it appears to be about". Nothing here inspects anything.
- **ADR-0199 §5** — the withholding is at supply; a deflection "carries no span of
  the withheld content and no value derived from it — not a paraphrase, a summary,
  a count over it, a category, a subject label, or any other value that narrows
  what was withheld"; and where nothing speakable remains an addressed turn "states
  that it cannot be given on this channel and carries nothing else".
- **ADR-0200 §7** — there is one *answer* on this call and `outcome.reply` is it;
  it is composed for this channel; no component filters, redacts or post-processes
  it; "no adapter applies, re-applies, relaxes or second-guesses ADR-0199's ruling,
  and none composes, substitutes or amends a deflection".
- **ADR-0200 §8** — no audio is retained by any component on this path, and the
  turn is captured exactly as ADR-0074 §3 captures every turn.
- **ADR-0037 §4** — `CONFIRM` parks the step and "the turn never answers on the
  user's behalf". ADR-0199 §5 reads the park and the deflection as "the same move:
  the turn declines to complete on this surface, says what it needs, and points at
  a place where the act can be taken." That reading is what makes the owner's
  "in the deflection's shape" a shape the corpus already holds.

### The tension a reader will find, and why it resolves the way it does

ADR-0200 §7 ends: "A turn on this operation is always addressed to the assistant,
so ADR-0199 §5's silence clause has no subject here: **this call never answers with
silence.**" ADR-0200 §4 rules that a park is silent. Read carelessly the two
collide; read as written they do not, because a park is **not an answer** — the
turn asks rather than answers, which is ADR-0037 §4's own statement of it. §7's
sentence is about what this operation does when it answers.

That reading survives this decision, and this decision makes §7's sentence more
nearly true rather than less: after it, the operation is audible on every shape a
listener can reach. **No record is owed on §7**, and §9 says so with the clause
quoted, because a reader checking §4's record will look for a companion there.

### An honest statement of what this ADR is not allowed to settle

- **Whether the planner should route a plain memory question through a
  confirm-owed tool at all.** #1699 notes the asymmetry — "a plain memory question
  parks on `recall_memory` CONFIRM" — and the owner's ruling holds it noted and not
  ruled. It stays on #1699. This decision makes the park audible; it does not make
  the park rarer, and a reader must not take it as endorsing the frequency.
- **What the browser page shows.** ADR-0200 §10's `POST /ask/spoken` and the page
  around it are a later lane's; the card already appears, and §8 declines to add a
  visual cue rather than deferring it silently.
- **Whether this or any other sentence is ever translated.** No localisation
  mechanism exists anywhere in this repository, and inventing one for one sentence
  would be the widest possible instrument for the narrowest possible need.

## Decision

### 1. A `converse_spoken` pass that parks on a confirmation is spoken, not silent

> **Normative.** On a `converse_spoken` pass whose `TurnOutcome` is a **live
> confirmation park**, `spoken` is the rendering of the one fixed sentence §2
> fixes, synthesised by the same stage, in the same chosen format and under the
> same bounds as an answer. It is not silence.

> **Normative.** A **live confirmation park** is exactly one of two shapes and no
> others: an `outcome` whose `step.disposition` is
> `Disposition.AWAITING_CONFIRMATION`, and an `outcome` whose `routed.outcome` is
> `RouteOutcome.AWAITING_CONFIRMATION`. Both are decided from those two recorded
> enum members and from nothing else — not from `reply` being `None`, not from the
> confirmation's content, not from the tool, the operation or the subject.

**Both shapes, because they are one thing to the person who asked.** #1699
measured the step park, but the routed park is the same user-facing event reached
by a different stage: a confirm-owed operation resolves, a card is minted, nothing
is composed, and the owner hears nothing. `_finish_route` gives the same reason for
both — "the confirmation is what the user must answer, and prose beside it competes
with the question" (ADR-0197 §10) — and ADR-0198 §6 rules the routed park exactly
as ADR-0197 §7 rules it rather than inventing a second regime for it. Ruling one
and not the other would leave the owner hearing silence on precisely the routed
operations `track:voice` exists to make reachable by voice.

**Deciding it from the disposition is what keeps ADR-0199 §2's decision procedure
satisfied by construction.** The two enum members are recorded outcomes of the
permission gate and the routing stage. Nothing is read out of the confirmation, the tool
declaration, the policy's `reason`, the resolved subject, or the words the user
said — so there is no content inspection anywhere on this path, and none can be
introduced by an implementation trying to be helpful.

**Deciding it from the disposition rather than from `reply is None` is also what
keeps the other two silences intact.** A composition failure and a recovered
resume both have `reply` `None`; neither is a park; neither becomes audible.

### 2. The sentence, its bytes, and where it lives

> **Normative.** The sentence is exactly:
> `I need you to confirm something on your screen.` — those bytes, that
> punctuation, that terminal full stop. It is handed to
> `SpeechSynthesizer.synthesize` byte for byte, exactly as an answer is.

> **Normative.** The sentence is **fixed by this ADR's text**. It is not composed,
> not model-authored, not templated, not derived from the park, and not
> configurable: no `Settings` field, no environment variable, no deployment value
> and no argument selects, varies or overrides it, and no later implementation
> substitutes another sentence without an ADR that supersedes this clause.

> **Normative.** It lives in `ai_assistant.orchestration`, as a module-level
> constant that subsystem owns. It is not a `core` type, not a member of one, not a
> field on `Settings`, not a member of the promoted engine surface, and not
> exported on the wire.

> **Normative.** This ADR states the posture ADR-0199 §3's fourth clause obliges it
> to state, for exactly one producer: the sentence above, authored by this project
> and fixed by this text, is **placed as speakable on a channel of unbounded
> audience**. The placement reaches that one constant and nothing else — not a
> family of sentences, not a second constant, not anything `orchestration`
> composes, and not the park's confirmation, its tool, its recorded reason or its
> resolved subject, each of which stays withheld exactly as it is today.

**The placement is owed because the sentence has no recorded origin, and saying so
is the honest reading rather than a technicality.** ADR-0199 §2's third clause
rules that "content whose origin the supplying component did not record has no
class, and content with no class is withheld from a channel whose audience is
unbounded", and §3's fourth clause names the remedy: "An ADR admitting a new
source, a new facet, a new notification producer, or **any other producer of
content that can reach an output channel** states the posture of what it produces
on a channel of unbounded audience, in its own text. It may not settle that
question by silence, and until it does, what that producer produces is withheld
from such a channel." A project-authored constant is such a producer, however
small, and settling it by silence is the one thing that clause forbids.

**Placing a constant is cheap and safe in a way placing a class is not**, which is
why this placement can be stated without weakening anything. ADR-0199 §3's naming
discipline exists so that "the next source to land … is [not] speakable on the day
it merges, by omission", and the decay it guards against is a placement over a
*class* whose future members nobody has read. This placement has exactly one
member and can acquire none: the bytes are §2's, and another sentence needs
another ADR. ADR-0199 §5 already composes a deflection out of project-authored
framing around placed content, and ADR-0197 §7 already puts "the adapter's own"
words around a card; this sentence is the same kind of thing with none of the
placed content in it. What §3's fourth clause asks is that the posture be stated
rather than assumed, and this is it.

**The text is normative because the text is the whole of the guarantee.** Every
disclosure property this decision claims — that it names no tool, no operation, no
subject, no step, no reason and no part of what the user said — is a property of
this string and of no rule that could be stated about a family of strings. A
sentence a deployment could vary is a sentence nobody has reviewed, and it would
put content selection back on a path this ADR is spending a supersession to keep
free of it. So the bytes are the ruling, as ADR-0197 §7 makes the card's wording
the adapter's own rather than a value.

**It is content-free in the only sense that matters here: it is a constant.** A
constant is a function of nothing, so no fact about the user, the park, the plan or
the memory store can be recovered from having heard it. What it does disclose is
that *a* park happened — which is not one of the classes ADR-0199 §3 withholds, is
the fact the owner asked to be told, and is already on the screen the sentence
names. The sentence itself is placed as speakable by the clause above, so nothing
here rests on it being unclassifiable.

**It names the screen unconditionally, and that is a decision taken about a
promoted-surface operation with the caller that has no screen at all in view.**
`converse_spoken` is on the promoted engine surface, so its callers are every
wire client there is or will be — a browser page, a CLI, a room speaker, a later
spoke with no display of any kind — and the sentence names a screen to all of
them. ADR-0199 §5's third clause makes naming a bounded channel conditional on
one being *nameable*, and this ADR deliberately does not inherit that condition.
The hub cannot know what surfaces its user is looking at, or whether the caller
has one, and §8 declines to build the instrument that would tell it; a
conditional naming would therefore have to be decided from an instrument nobody
has, and on a caller it could not resolve it would say either less than the
owner's ruling fixed or nothing at all — which is #1699's silence returning on
precisely the deployments this decision exists for. The corpus has stood at this
fork before and did not resolve it by neutering the sentence: ADR-0199 §5 kept
the *stating* unconditional while making only the *naming* conditional, because
"a room speaker with no browser open and no other enrolled device is the state a
household kitchen is in most of the day", and its own model sentence — "details
on your phone" — names, from that same promoted surface, a surface the operation
neither renders nor can see.

**What the sentence asserts is where the park is answerable, not what the caller
can draw, and it promises nothing about how long the card waits.** It is true at
the moment it is spoken: a confirmation was minted, its durable state is written,
and it is answerable on a screen — reached through the card the same result
carries and through `resume`, on whatever surface its user next opens. It
asserts nothing about later, and no reader takes it as a durability guarantee.
It is equally no claim that `converse_spoken` renders anything: §5 adds no
presentation capability, no display obligation and no ordering guarantee to the
promoted surface, and the sentence does not need one to be true.

**The two parks' lifetimes are what the corpus already made them, and this ADR
moves neither.** A step park's is `confirmation_ttl`, which "defaults to `None`"
because ADR-0037 §4 declined to invent a lifetime, and which a deployment may set.
A routed park's is `routed_confirmation_ttl`, "positive and finite, with no
spelling for 'never'" and fifteen minutes by default, because a routed park is
invisible to `pending_confirmations` and would otherwise hold a ceiling slot
forever (ADR-0197 §7). Where a card has gone stale by the time the user reaches it,
`resume` refuses it as `UnknownContinuationError`, whose case set ADR-0198 §5
fixes — exactly as it refuses a card reached late on the typed channel, which is
the behaviour today and which §8 leaves alone.

**It is in the deflection's shape and it is not a deflection.** ADR-0199 §5 governs
an answer on a turn where a class was withheld; here nothing was withheld and no
answer was owed. The borrowing is of the *form* the owner named — say what is
needed, name where the act can be taken, carry nothing else — which ADR-0199 §5
itself derives from the parked confirmation. No clause of ADR-0199 §5 is applied,
relaxed or re-applied by this ADR, and §9 records that none is owed against it.

### 3. What differs from ADR-0200 §4, stated whole and bounded

> **Normative.** The whole of the difference this ADR admits is: on a live
> confirmation park, `spoken` may be non-`None`; it is then the rendering of §2's
> sentence; and `spoken_degraded` follows §4 below instead of being pinned `False`.
> Nothing else about a parked `SpokenTurn` differs. No lane reads this clause as
> licence for a second difference.

> **Normative.** `outcome` is unchanged on a park in every member. `reply` stays
> `None`, `reply_degraded` stays as the pass set it, the step, the routed account,
> the conversation and its id, `capture_degraded` and the turn are what the pass
> produced. The sentence is not an answer, is never written to `reply`, and no
> component copies it there.

> **Normative.** `heard` is unchanged, and is disclosed on a park exactly as
> ADR-0200 §4 obliges it on every call that produced a transcript.

> **Normative.** The recovered resume and the composition failure keep ADR-0200
> §4's silence in full: `spoken` is `None`, `spoken_degraded` is `False`, and
> nothing is invented to fill it. This ADR reaches neither.

**Keeping the sentence out of `reply` is the load-bearing half.** `TurnOutcome.reply`
is "the natural-language answer the turn composed, and **the only place an answer
is carried**" (ADR-0170 §3), documented as `None` on exactly the three shapes
above. Writing a sentence nobody composed into that member would make an
uncomposed constant indistinguishable from an answer for every consumer of
`TurnOutcome` — the typed channel, the streaming turn, the captured episode, the
restatement machinery of ADR-0198 — in order to make one operation audible. It
would also convert a change scoped to `SpokenTurn` into a change to what `reply`
means everywhere. The rejected alternative is recorded under "Alternatives
considered".

**What is spent to buy this is one sentence of ADR-0200 §4, and it is worth
naming rather than eliding**: "A caller that cannot play audio reads
`outcome.reply` and holds exactly what was said." On a park that stops being true.
It costs nothing measurable, because what was said is a **constant fixed by this
ADR** and the park is legible on the outcome from `step.disposition` or
`routed.outcome` — so nothing about the call becomes unknowable, and the caller
reads the card besides, which carries strictly more than the sentence does. **That
is an argument about loss and not an instruction**: no caller is obliged to
reconstruct the sentence and none is licensed to carry it, which §5 rules rather
than leaves to inference. It is the one place in this decision where a ratified
guarantee is narrowed rather than kept, and §9 classifies it.

### 4. `spoken_degraded` on a park: ADR-0200 §4's ladder, unchanged, over a wider subject

> **Normative.** On a live confirmation park `spoken_degraded` is `True` **exactly
> when** §2's sentence existed and speaking it did not complete, which is ADR-0200
> §4's four cases and no others: synthesis raised; the format intersection of
> ADR-0200 §3 was empty; the rendering would have breached ADR-0200 §6's bound; or
> the complete `SpokenTurn` carrying that rendering would breach ADR-0085 §8c's
> payload limit. It implies `spoken is None` and `outcome is not None`.

> **Normative.** Every other clause of ADR-0200 §4's degradation ladder binds on a
> park unchanged and is not restated here: the fourth case measured on the whole
> projected result, the second measurement raising `OversizedValueError` where the
> result still breaches §8c with no rendering in it, the `TurnOutcome`-alone
> breach, the transcription-fails/synthesis-degrades line, the total translation at
> the orchestration boundary, and the cancellation clause.

> **Normative.** A park whose sentence could not be spoken is therefore `spoken`
> `None` with `spoken_degraded` `True` beside an `outcome` whose `reply` is `None`
> — a shape ADR-0200 §4 pinned to `False` and this ADR admits, and the second half
> of what §6's validator must be widened to accept.

**This is the same ladder reading a wider subject, not a second ladder.** ADR-0200
§4's predicate is "an answer existed and speaking it did not complete"; after this
decision the antecedent on a park is the fixed sentence rather than an answer, and
every consequent is untouched. Pinning `False` instead would report a park whose
synthesizer raised identically to a park whose synthesizer succeeded, which is the
state ADR-0200 §4 built the flag to prevent: "a stage that could be wholly broken
while every call reported the same classified-looking degradation is the state
hardest to notice."

**ADR-0203 said this clause was not replaced, and that remains true of ADR-0203.**
ADR-0200's header note records that ADR-0203 leaves the ladder's "rule and its
shape… exactly as §4 wrote them, §4's exactly-when clause for `spoken_degraded`
included". That is a statement about what ADR-0203 does. This ADR moves the
predicate's antecedent on one shape, says so on the same header, and moves nothing
ADR-0203 moved.

### 5. Nothing else on this path moves

> **Normative.** `SpokenTurn` gains no member from this decision and loses none.
> Its members are the four ADR-0200 §4 fixed and the fifth ADR-0205 §1 added —
> `heard`, `outcome`, `spoken`, `spoken_degraded` and `episode_id` — and the type
> stays frozen and `extra="forbid"`. This ADR moves the *shapes* those members may
> take on a park (§6) and moves the member set not at all.

> **Normative.** The park itself is unchanged: the same step is parked, the same
> continuation handle is minted, the same `Confirmation` or `OperationConfirmation`
> is assembled and carried, the same durable state is written, and `resume`,
> `pending_confirmations` and ADR-0198's restatement are untouched. Nothing about
> the routing stage, the permission gate or the planner is decided here.

> **Normative.** One `SpokenTurn` carries both the parked `outcome` — with the
> `Confirmation` or `OperationConfirmation` a surface renders the card from — and
> §2's rendering, on the same result of the same call. A caller therefore holds
> the card before it can play anything, and **the order in which it presents the
> two is the caller's own**. This ADR creates no ordering obligation between
> them and adds none to the promoted surface: nothing here requires a client to
> render before it plays, to play before it renders, to render at all, or to
> report either act. A surface that plays the sentence and draws nothing, and a
> surface that draws the card and plays nothing, each satisfy this decision.

> **Normative.** Capture is unchanged. The sentence is not composed, not an answer
> and not part of the exchange: no episode carries it, no field is added to
> `EpisodicMemory` or to `Provenance`, and ADR-0074 §4's rendering of a parked
> exchange — "the action was parked for the user to confirm" — is what the record
> says, exactly as it says it today.

> **Normative.** ADR-0200 §8 binds unchanged: no audio, neither the utterance nor
> the rendering of §2's sentence, is written to any store, index, trace, audit
> trail, routing trail, outbox or log, in either tier, by any component on this
> path.

> **Normative.** `ai_assistant.orchestration` **owns** the sentence and the choice
> to speak it. No other component declares it, holds a second copy of it, persists
> it, displays it, substitutes another for it, or decides when it is spoken: no
> adapter under `interfaces/`, no client under `wire/`, no page, no `Settings`
> field and no later spoke. A surface that cannot play audio shows the card, which
> is what it shows today.

> **Normative.** That ownership rule bounds **authorship and selection**, and three
> things it does not reach are named so the contract is satisfiable. **(a) The
> injected synthesizer receives it**, as one-way input, which is §2's mechanism and
> not a second owner — `SpeechSynthesizer` is a seam beside the model provider
> (ADR-0200 §1, §2), so the value crossing into it is the same crossing every
> answer already makes. **(b) `SpokenTurn`'s validator reads §1's two enum
> members** under §6; that is structural validation of which shapes a `core` type
> admits, and it never reads the sentence. **(c) The canonical `FakeAssistantEngine`
> in `ai_assistant.testing` names the same `orchestration` constant** — the one
> object, imported, never re-declared — so the double returns a legal parked
> `SpokenTurn` and cannot drift from the engine it stands in for.

> **Normative.** ADR-0199 §5's silence clause for an unaddressed emission is
> untouched and has no subject here. A `converse_spoken` turn is addressed to the
> assistant by construction. The delivery path is ADR-0206's, and this ADR reaches
> none of it: a withheld notification still "arrives unspoken" with "no audible
> substitute of any kind, chime, tone or spoken notice included" (ADR-0206 §5), and
> §2's sentence is not that substitute, is not spoken on a delivery, and is not
> cited toward one.

> **Normative.** This ADR admits **no component that assembles what a channel of
> unbounded audience is composed from**, which is what ADR-0204 §3's second clause
> obliges an ADR in this position to state rather than settle by silence. §2's
> sentence is a constant: it is assembled from nothing, reads no record, and adds no
> supply site. So ADR-0204 §3's `supplied_withheld_content` test has no subject
> here — it is neither applied to the sentence nor weakened by it — and every supply
> site that test already governs governs unchanged.

> **Normative.** ADR-0205's delivery machinery binds a park unchanged. Capture on
> this operation still writes `SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)`
> onto the turn's index row "unconditionally on that operation — including where the
> answer was parked" (ADR-0205 §4), a device may report on a parked turn by the
> `episode_id` that turn carries, and §5 of that ADR supplies the fact to a later
> composing stage exactly as it supplies any other. Nothing here writes, reads,
> defaults or infers a delivery state, and nothing reads one to decide what is
> spoken.

**No ordering guarantee is added, because none is needed and the corpus has
none to add.** The sentence says where the park is answerable; it does not claim
that anything has already been drawn, so a client that draws the card after it
plays the audio, or long after, or never, does not make it false — the card
travels on the same result and the park is answerable from the moment its
durable state was written. This is the position ADR-0199 §5's deflection has
been in since it was ratified: "details on your phone" is spoken on one channel
about a surface the promoted operation neither renders nor sequences, and
nothing was added to that surface to support it. Adding one here would mean a
presentation or ordering capability on the promoted engine surface — a contract
nobody has ruled, and a far larger decision than the one this ADR makes — which
is why §8 declines the visual cue on the same ground. What a caller is handed is
ADR-0200 §4's `SpokenTurn` and nothing more, and that is enough.

**The fake names the constant rather than copying it, and the edge already
exists.** `ai_assistant.testing`'s engine double imports from
`ai_assistant.orchestration.payloads` today, and the contract that governs this
direction is the one forbidding *production* code to import the doubles, not the
reverse. So the double can satisfy §6's third arm with the same object the engine
synthesises, which is the only arrangement under which "the fake and the engine
say the same thing" is a property rather than a hope. A copied literal in
`testing/` would be the drift golden rule 1 exists to prevent, arriving through
the package whose job is to make the contract testable.

**The ownership clause is golden rules 1 and 3 applied to a string, and it is
worth a ruling rather than an assumption.** A constant an adapter could copy is a
rule an adapter has re-decided: to render it, `interfaces/` would have to hold both
the literal and §1's park test, which is business logic in a layer that is supposed
to have none, and the two copies would drift the first time either moved. Keeping
the sentence in one package makes the audio the only place it appears, which is
also why §8 declines a visual cue: the card is the screen's answer and the sentence
is the speaker's, and neither needs the other's copy.

### 6. The contract surface this decision moves, and how the validator is widened

> **Normative.** `SpokenTurn`'s `model_validator` in `core/types.py` is **widened,
> not deleted**. Its admissibility test changes from "`outcome` is not `None` and
> `outcome.reply` is not `None`" to that disjoined with "`outcome` is a live
> confirmation park in §1's sense"; every other arm stays and stays stated both
> ways. In particular the validator still refuses a rendering, and still refuses
> `spoken_degraded`, beside a `reply`-less outcome that is **not** a park — a
> recovered resume or a composition failure — and still refuses `spoken_degraded`
> beside a non-`None` `spoken`, and still refuses `heard` and `outcome` present
> apart.

> **Normative.** The widened validator gains a **third arm** in the same change: on
> an outcome that *is* a live confirmation park it refuses `spoken` `None` beside
> `spoken_degraded` `False`. On such a park the sentence is either rendered (§1) or
> one of §4's four cases fired, and there is no third state — so the silent park
> ADR-0200 §4 used to require becomes a shape the type does not admit, and an
> implementation that skipped synthesis and returned the old pair fails at
> construction instead of crossing the wire.

> **Normative.** All three arms range over `outcome`, `spoken` and
> `spoken_degraded` and read no other member. `episode_id` (ADR-0205 §1) is
> orthogonal to every one of them: it is present or absent on its own terms, no arm
> tests it, and no arm is relaxed or tightened by it. Whichever of the two lanes
> lands second widens the validator it finds rather than the one its ADR described.

> **Normative.** The type's own docstring is corrected in the same change, so that
> a reader of `core/types.py` is not left with a sentence the validator no longer
> enforces. Nothing else in `core` moves: no new type, no new field, no new
> `StrEnum` member, no signature, no Protocol and no member of one.

> **Normative.** `FakeAssistantEngine.converse_spoken` renders the same sentence on
> a scripted park, by the same rule and with the same degradation ladder, so the
> double satisfies the widened validator rather than being exempted from it. Its
> rendering stays what it already is — deterministic, opaque octets derived from
> the text it was handed — and nothing decodes one.

> **Normative.** This is the whole of the contract surface this decision touches.
> No `Settings` field, no error class, no wire operation, no `FrameKind`, no
> frame's encoding, no envelope member and no method's arguments or results.

**Widening rather than deleting is the point of stating it.** The cheap
implementation of §1 is to drop the two checks, and it would pass every test a
lane wrote for the park while silently readmitting the two shapes the validator
was built to refuse — "a rendering beside no answer would be audio of something
this type does not hold". The park is decidable from the outcome the type already
carries, so the check stays total; it just knows about one more legal shape.

**And the third arm is what keeps it total in the other direction.** Widening
admissibility alone would leave `SpokenTurn(heard=…, outcome=<a live park>,
spoken=None, spoken_degraded=False)` a legal value — precisely the result #1699
measured, and precisely what this ADR exists to stop producing. Without the arm, a
regression that skipped the park branch would construct, project and cross the wire
as an ordinary result, and only a test of the engine would catch it. With it, the
type refuses, which is the property ADR-0200 §4 built the validator for: it is
"stated **both ways**, because each direction rules out a different lie".

**The docstring correction is not cosmetic.** `SpokenTurn`'s docstring today
asserts "**`spoken` is the rendering of `outcome.reply` and of nothing else**…
a caller that cannot play audio reads `outcome.reply` and holds exactly what was
said", which is the ratified sentence §3 narrows. Leaving it would put a false
statement in the file a client reads first, and ADR-0088's citation discipline is
worth nothing if the cited text is stale.

### 7. `PROTOCOL_VERSION` moves, and the implementing lane owes the arithmetic

> **Normative.** The change implementing this decision bumps `PROTOCOL_VERSION`,
> in that same change, and appends its own note to the running record in
> `wire/envelope.py` in the established form. The obligation is on that lane; the
> value is whatever the constant then holds plus one. **ADR-0205's implementing
> lane bumps it too** — its fifth `SpokenTurn` member and its fifth
> `converse_spoken` argument are ADR-0124 §9's first and second limbs both — so the
> two bumps **compose and do not collide**: whichever lands second reads the
> constant as it then stands and adds one, and each writes its own note. Neither
> lane waits on the other and no lane merges the two notes into one.

> **Normative.** The `core/types.py` widening of §6, the `orchestration` change of
> §§1–2, the canonical fake's matching change in `ai_assistant.testing` (§5), and
> the bump above land in **one** lane and one PR. The fake is not a follow-up: a
> widened validator with a double that still returns the old pair is a suite that
> fails the moment either lands without the other. A build carrying the
> bump while still refusing the shape it was bumped for, or carrying the shape
> while still speaking the old version, is a half-finished upgrade with no reader.

> **Normative.** Nothing else under `wire/` changes for it. The framing, the
> connect exchange, the frame kinds, the codec's dispatch, the error registry, the
> method set and both adapters are untouched: a result payload takes the shape of
> the method's declared return annotation (ADR-0085 §10), which is unchanged.

**It is ADR-0124 §9's second limb, and the widening direction is exactly the one
that limb exists for.** The rule bumps on "a change to a wire-carried `core` type
that makes a value one peer emits invalid for the other, **whether the change
widens or narrows the type**", and ADR-0124 §9 names the case the corpus was
already caught by: ADR-0122's widening, where "read as 'narrowing bumps, widening
is safe', the rule would have got that case wrong". Here a hub at the new version
emits a `SpokenTurn` carrying `spoken` beside a `reply`-less park, and a client at
the old version reconstructs it through the validator quoted in the Context and
fails. One direction is enough: "the test is whether *some* frame one side may
send is unacceptable to the other, in either direction."

**A conforming peer at the old version really is refused, which is what makes this
a bump rather than a widening one side absorbs.** `wire/client.py`'s
`converse_spoken` is annotated `-> SpokenTurn`, so the payload is validated on
arrival; ADR-0084 §3's exact-match handshake is the mechanism that turns that into
a legible refusal naming both versions instead of a `ValueError` inside a call.
The operational cost is one redeployment, hub and clients together, which
ADR-0178 §6 names rather than minimises.

### 8. What this decision does not decide

> **Normative.** The routing asymmetry #1699 records — that a plain memory question
> is routed through a confirm-owed tool and so parks where the typed channel would
> not — is **not decided here**. It stays noted on #1699. Nothing in this ADR is
> cited toward changing which steps park, which tools carry `CONFIRM`, or what the
> planner reaches for.

> **Normative.** No visual cue is added to any surface. The confirmation card
> already appears on the screen the sentence names, and this ADR adds no page
> element, no field for one and no obligation on `interfaces/`. A later ADR may add
> one; this one declines rather than defers.

> **Normative.** No spoken resume is added. `converse_spoken` still resumes nothing,
> and answering the confirmation stays `resume` on a channel of bounded audience.
> An owner who hears the sentence answers on the screen.

> **Normative.** The sentence is not localised, translated or varied by locale, and
> no mechanism for doing so is created, implied or reserved by this ADR.

> **Normative.** Neither park's lifetime moves. `confirmation_ttl`,
> `routed_confirmation_ttl`, ADR-0197 §7's eviction and ADR-0198 §4's retention are
> what they were, and nothing here re-reads a clock, re-checks answerability after
> synthesis, suppresses the sentence for a park that expired while it was being
> spoken, or makes what is said depend on how long anything took. §2's sentence is
> spoken on the shape the pass reached; a card that goes stale afterwards is refused
> at `resume` exactly as it is refused today.

> **Normative.** Nothing here authorises egress, relaxes a permission floor, or is
> cited toward a designation, a registration or a destination. The one placement
> this ADR makes under ADR-0199 §3 is §2's single constant, bounded there:
> ADR-0199 §3's Tier 0 floor, its three withheld classes, its three placed classes
> and its notification clauses are untouched, and no class of recorded content
> becomes speakable by anything decided here.

**The lifetime decline has a residual and it is filed rather than buried.** A park
registered before a synthesis is answerable for one synthesis less than it was, and
#1714 records that with the figures — fifteen minutes by default for a routed park,
no expiry at all by default for a step park, a legible `UnknownContinuationError`
where the race is lost, and the registration-to-delivery gap that already exists on
`converse`. "Alternatives considered" states why every way of closing it is worse
than the window.

### 9. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is ADR-0070 §1's applied to the earlier ADR's text: would a
reader holding only that ADR now act differently, or read one of its clauses more
widely than it now holds? ADR-0200's `Status` already carries the leading
`Partially superseded by` token and one pair, by ADR-0203; this ADR's pair joins it
under ADR-0070 §4's accumulation rule, without dropping that one, and the substance
goes in the appended dated note ADR-0070 §1 requires in every case. The header
bullet above carries the grounding for the timing and the place.

**ADR-0200 §4's park clause — a record is owed, and it is a partial supersession.**
The clause reads: "`spoken` is `None` wherever `outcome.reply` is `None`: a park, a
recovered resume, and a composition failure each leave nothing to say, and nothing
is invented to fill the silence. On those shapes `spoken_degraded` is `False`." A
reader holding only ADR-0200 writes what `main` carries: `if reply is None: return
None, False`, and a validator that refuses anything else. After this decision they
render a sentence on one of the three shapes and let the ladder run over it. That
is a reader acting **differently**, which is ADR-0070 §1's line, so it is a
supersession, and partial supersession is the sanctioned form (ADR-0070 §3). It is
**narrow**: the clause governs unchanged on the recovered resume and on the
composition failure, and §3 above keeps them in terms.

**ADR-0200 §4's rendering clause — a record is owed, on the same ground.** "`spoken`
is the rendering of `outcome.reply` and of nothing else… A caller that cannot play
audio reads `outcome.reply` and holds exactly what was said." On a park `spoken`
is now the rendering of §2's sentence, and the parity sentence becomes false there.
The clause is otherwise untouched — on every non-park pass `spoken` is still the
rendering of `outcome.reply` and of nothing else, there is still exactly one
*answer* and it is still `outcome.reply`, no second copy of the spoken words is
carried anywhere, and the synthesizer's obligation that the audio is an audible
rendering of the text handed to it is unchanged and still discharged in its
conformance suite.

**ADR-0200 §4's `spoken_degraded` exactly-when clause — a record is owed, and it is
the narrowest of the three.** Its antecedent, "an answer existed", is on a park
satisfied by §2's sentence instead. Four cases, the implication of `spoken is None`
and `outcome is not None`, the never-`True`-beside-a-rendering clause, both payload
measurements and both `OversizedValueError` arms are untouched, and §4 above says
so rather than restating them.

**ADR-0200 §7 — no record is owed, and it is worth stating rather than omitting**,
because it is the section a reader will check first. Its third clause — "There is
**one** answer on this call and `outcome.reply` is it" — stays true word for word:
§2's sentence is not an answer, is not composed, and is never written to `reply`.
Its second clause (the withholding is at supply; nothing filters, redacts or
post-processes `outcome.reply`) has no subject on a park, where no reply exists to
filter. Its fifth clause — "The deflection reaches the user **as speech on this
channel**… this call never answers with silence" — is the one this decision makes
*more* nearly true, and a reader acting on it as written would already have been
uneasy about the measurement on #1699. Its sixth clause, that no adapter composes,
substitutes or amends a deflection, binds this ADR too and is obeyed: §2's sentence
is not a deflection and no deflection is touched. Recorded here because ADR-0082 §1
forbids a record demanded on book-keeping grounds alone, and this is the argument
that none is owed.

**ADR-0200 §8 — no record is owed.** Its retention clauses have this ADR's
rendering as a new subject and rule it exactly as they rule an answer's: nothing is
retained. Its capture clause is restated and obeyed by §5 above rather than
narrowed.

**ADR-0199 §2 and §3 — no record is owed, because §3 provides for this and this ADR
uses the provision.** §2's decision *procedure* is satisfied by construction: §1
above decides from two recorded enum members and inspects no content. §2's third
clause — content whose origin was not recorded has no class and is withheld — does
reach §2's sentence, and §3's fourth clause names what an ADR in that position owes
and what happens until it pays: the posture is stated in the admitting ADR's own
text, and "until it does, what that producer produces is withheld". §2 above states
it. A reader holding only ADR-0199 reads "withheld **until** an ADR places it", and
is not made to act differently by an ADR that places one constant in exactly the
manner §3 prescribes — that is ADR-0082 §1's stacked addition, "recorded in the ADR
that makes it, and nowhere else", rather than a sentence of ADR-0199 becoming false
or over-wide. Nothing else of §3 moves, and §8 above says so in terms.

**ADR-0199 §5 — no record is owed.** Its deflection clauses govern an answer
composed where a class was withheld and have no subject here; its silence clause
governs an unaddressed emission and has none either; its fan-out clause and its
bounded-to-unbounded clause are untouched, and §5 above restates the first two.
This ADR borrows §5's *shape*, which is not an act §5 regulates.

**ADR-0170 §3 and §4 — no record is owed.** `reply` remains the only place an
answer is carried and remains `None` on the three shapes ADR-0170 and
`core/types.py` name; `reply_degraded` is untouched. §3 above forbids in terms the
one construction that would have moved them.

**ADR-0197 §7 and §10, ADR-0198 §6, ADR-0037 §4, ADR-0052 — no record is owed.**
The park, its card, its handle, its durable state, its retention and its resumption
are unchanged; this decision reads two recorded dispositions and adds a sentence
beside them. ADR-0197 §7's "no model-written text" is the pattern §2 follows.

**ADR-0124 §9 — no record is owed; it is applied.** §7 above states the bump its
second limb requires, which is compliance, not amendment.

**ADR-0205 — no record is owed, and the near miss is worth naming.** Its §1
member and argument counts are untouched: this ADR adds neither. Its §4 first
clause — capture writes `UNKNOWN` "unconditionally on that operation — including
where the answer was parked" — is unchanged and is what §5 above restates. What
this decision does touch is a **characterisation inside** §4's fourth clause, which
opens "A turn whose rendering never existed — a park, an `outcome.reply` of `None`,
synthesis raising, an empty format intersection, a breached bound (ADR-0200 §4) —
stays `UNKNOWN` and is **not** left absent." After this ADR a park's rendering
*does* exist, so the park is no longer an instance of the antecedent it is listed
under. Apply ADR-0082 §1's test to the clause rather than to the phrase: the
obligation is "stays `UNKNOWN` and is not left absent", a park still carries
`UNKNOWN` — §4's first clause says so on its own, without the enumeration — and a
reader acting on §4 writes exactly the same value before and after. They act
**identically**, which is ADR-0070 §1's line, so no record is owed and §4's other
four members of that list are unaffected. It is a stale characterisation and not a
stale decision; it is recorded here, in the ADR that made it stale, which is
ADR-0082 §1's own instruction for a change that fails no clause's test.

**ADR-0204 — no record is owed; §3's second clause is obeyed.** That clause obliges
an ADR admitting a component that assembles what an unbounded channel is composed
from to say that the test applies there "rather than settling the question by
silence". §5 above says this ADR admits no such component and why — a constant is
assembled from nothing. Saying so is compliance with §3, not a change to it, and
§3's supply-site test, §1's field, §4's bounded-channel clause and §5's
never-clears rule all bind unchanged.

**ADR-0206 — no record is owed.** It decides the delivery direction and this ADR
decides an answer-side operation; neither reaches the other. Its §5 rules that a
withheld notification arrives unspoken with no audible substitute, and §5 above
states in terms that §2's sentence is not one and is never spoken on a delivery. Its
§3 placement is over `NotificationCandidate`'s three recorded values and is neither
widened nor narrowed by §2's placement of one constant.

**ADR-0085 §8c, ADR-0200 §3 and §6 — no record is owed.** The payload limit, the
format intersection and the two byte bounds govern §2's rendering exactly as they
govern an answer's, which is §4 above's second clause.

**Where §2's bytes come from, recorded so that no later reader takes them for a
drafting choice.** The sentence is the owner's product ruling on #1699 of
2026-08-28 — "a fixed, content-free sentence in the deflection's shape (*I need
you to confirm something on your screen*)" — carried into this ADR unchanged.
Everything else here is a technical decision, open to review and to supersession
in the ordinary way; the string is not one of them. Different words are a
product decision, and reaching them means a ruling and an ADR that supersedes
§2, not an editorial pass over this text. What review can properly reach about
the sentence is answered above rather than left open: the promoted-surface
generality and the caller with no screen in §2, the ordering and the absence of
any presentation capability in §5, and the ADR-0199 §3 placement in §2.

**This ADR is marked under ADR-0089**, so its marked clauses are the whole of what
it obligates and the prose beside them determines what they mean.

## Consequences

**The exit test milestone 19 turns on gets easier to trust and one more shape gets
easier to debug.** A listener can now tell "the hub parked" from "the hub is down",
which is the distinction #1699 records as unavailable from the phone. The failure
mode this closes is not exotic: it is the ordinary case of asking a memory question
that the planner routes through a confirm-owed tool.

**One ratified guarantee is narrower than it was.** A caller of `converse_spoken`
that cannot play audio no longer reconstructs what was said from `outcome.reply`
alone on a park; it reconstructs it from `outcome` plus this ADR's §2. That is a
real cost and §3 states it in the decision rather than in the consequences, so a
later reader finds it where the rule is.

**The implementing lane crosses four packages, and §7 decides that it is one
lane.** `core/types.py` (the validator and the docstring), `orchestration/` (the
constant and `_spoken_rendering`'s park branch), `testing/` (the canonical fake,
naming that same constant), and `wire/envelope.py` (`PROTOCOL_VERSION` and its
note). That is the same grouping ADR-0200 §13 made for
the same surface and for a reason that transfers: the bump is owed "in that same
change" as the widening (ADR-0124 §9), and a build that has bumped the protocol
while still refusing the shape the bump was for is a deployment nobody wants to
own. It is not a licence to touch anything else.

**A redeployment is owed.** Hub and clients do not interoperate across the bump,
and the deployed hub plus the laptop's gateway both move together (ADR-0178 §6).

**The implementing lane owes these tests, and each is a shape rather than a line of
coverage.**

> **Normative.** The implementing lane pins: (a) a `converse_spoken` pass whose step
> parks returns `spoken` non-`None`, and the value handed to the synthesizer is §2's
> sentence byte for byte; (b) the same for a pass whose **routed** operation parks;
> (c) `outcome.reply` is `None` and `spoken_degraded` is `False` on both; (d) a
> composition failure still returns `spoken` `None` and `spoken_degraded` `False`;
> (e) `SpokenTurn` admits both park shapes with a rendering and still refuses a
> rendering beside a non-park `reply`-less outcome; (f) nothing derived from the
> park — no confirmation content, no policy `reason`, no tool id, no routed subject,
> no part of the transcript — reaches the synthesizer on any of them; and (g) a live
> park carrying `spoken` `None` beside `spoken_degraded` `False` is refused at
> construction, which is §6's third arm and the shape #1699 measured. Row (g) is
> pinned over **both** of §1's shapes, the step park and the routed one, as (a) and
> (b) are: §6's third arm ranges over §1's definition and not over one member of
> it, and an arm that refused the silent step park while admitting the silent
> routed one would pass a singular test while letting #1699's silence cross the
> wire on exactly the routed operations §1 was widened to reach.

> **Normative.** Both park shapes are exercised in the **shared `AssistantEngine`
> conformance suite** (`tests/orchestration/assistant_engine_contract.py`), so the
> canonical fake and the concrete engine are held to one statement of §1 rather
> than to two, and a double that returned the old silent pair fails the suite it
> is meant to certify.

> **Normative.** The lane pins **all four** of §4's degradation cases on a park, and
> not the two an implementation reaches first: synthesis raising; an empty format
> intersection; a rendering over ADR-0200 §6's bound; and the projected `SpokenTurn`
> over ADR-0085 §8c's payload limit — each asserting `spoken` `None` with
> `spoken_degraded` `True`. It pins the second measurement beside them: a parked
> result still over §8c with no rendering in it raises `OversizedValueError` rather
> than degrading further, and `heard` is not shortened to make it fit. Two of the
> four had no subject on a park before this decision, so an implementation that
> handled the two obvious ones and dropped an oversized park rendering with
> `spoken_degraded` `False` would breach §4 while passing every other row here.

> **Normative.** The lane pins the sentence's bytes in exactly one place: a test
> asserts the constant against the literal, and every other test refers to the
> constant. A suite that spelled the sentence out four times would make the next
> wording change look like four decisions.

## Alternatives considered

**Write the sentence into `outcome.reply` on a park.** This is the shape that needs
no `SpokenTurn` change at all: the composing stage is skipped, a constant is
written to `reply`, and everything downstream renders it. **Rejected**, and it is
the alternative closest to being right. `reply` is "the natural-language answer the
turn composed, and **the only place an answer is carried**" (ADR-0170 §3), `None`
on exactly three documented shapes; a constant nobody composed sitting in it would
be indistinguishable from an answer to every consumer of `TurnOutcome` — the typed
channel, the streamed turn, the captured episode, ADR-0198's restatement — none of
which asked for it and all of which would then have to be told about a fourth kind
of `reply`. It would also make the typed channel say a sentence about a screen the
typed caller is already looking at. Changing `SpokenTurn`'s admissible shapes costs
one validator and one bump; changing what `reply` means costs every reader of it.

**Compose the sentence instead of fixing it.** Let the composing stage run on a
park and produce something contextual. **Rejected on ADR-0199's own ground.** A
composed sentence is authored over the park's inputs, so what it says is a function
of the tool, the reason and the subject — exactly the values ADR-0199 §5 forbids a
deflection to narrow toward — and checking that it did not would be the content
inspection §2 forbids as a decision procedure. It would also spend a model call on
a turn that ADR-0197 §10 rules "owes no answer at all".

**Speak the confirmation itself.** Read the card aloud: "shall I look up what you
take in your coffee?" **Rejected.** It is the most useful thing that could be said
and it is the one thing this channel may not say: the card carries the tool
declaration, the policy's recorded reason and, on a routed park, the resolved
subject — content whose class is decided from origin and which an unbounded channel
withholds. It would also make the sentence's disclosure vary with the park, which
is what §2's constant exists to prevent.

**Rule the step park only, and leave the routed park silent.** **Rejected.** It
matches #1699's measurement and nothing else. The two parks are one event to the
person who asked, `_finish_route` gives them the same reason for owing no answer,
and ADR-0198 §6 already declines to invent a second regime for the routed one. The
asymmetry would land hardest on precisely the operations `track:voice` wants
reachable by voice.

**Pin `spoken_degraded` `False` on a park, whatever synthesis did.** It keeps
ADR-0200 §4's exactly-when clause word for word and is one fewer record. **Rejected.**
It would report a park whose synthesizer raised identically to one that succeeded,
which is the state ADR-0200 §4 built the flag to make impossible, and it would make
the flag's meaning depend on a shape rather than on what happened.

**Re-check the park's answerability after synthesis, and speak only if it is still
live.** The window between registering a park and delivering its rendering is real,
and this decision widens it by one synthesis of one short sentence. **Rejected**,
and not because the window is negligible — because every available response to it
is worse than the window. Speaking nothing when the check fails restores the exact
silence #1699 filed. Speaking a *second* sentence — "that expired, ask again" —
makes what is said a function of a clock, so the constant §2 buys stops being a
constant and the disclosure argument has to be made again over a family of
sentences. And the check itself would have the engine read a clock after synthesis
to decide what to say, on a path ADR-0200 §4 keeps free of anything but the ladder.
The residual is bounded and already legible: a stale card is refused at `resume`
as `UnknownContinuationError` (ADR-0198 §5), which is what a card reached late on
the typed channel does today. §8 states the decline rather than leaving it
inferable, and the residual is filed rather than buried.

**Delete the validator's two checks instead of widening them.** **Rejected**, and
named because it is what an implementation will drift toward: it passes every test
written for the park and silently readmits a rendering beside a composition
failure, which is audio of something the type does not hold. §6 states the widening
as the ruling so the drift is a review finding rather than a judgement call.
