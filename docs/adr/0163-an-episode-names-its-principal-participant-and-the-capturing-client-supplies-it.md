# 163. An episode names its principal participant, and the capturing client supplies it

- Status: Proposed
- Date: 2026-08-19
- **Decides one field in `src/ai_assistant/core/types.py` and no Protocol member —
  flagged under golden rule 5 rather than smuggled.** `EpisodicMemory` grows one
  optional field (§1). No Protocol signature moves, no member is added, no
  `Settings` field appears, and no existing field changes shape or meaning. The
  required review set is **adversarial and architecture**, because a `core` type's
  fields are contract surface and because §5 and §6 rule *against* surface — a
  `MemoryStore` predicate, a `MemoryPolicy` input, a validator — and a ruling
  against surface binds the implementing lane's surface as firmly as a ruling for
  one. **No triad is owed**: `CONTRIBUTING.md` → "Adding a Protocol" binds a *new*
  Protocol, and this ADR adds none. **No code changes with this ADR**; the
  implementation is [#1210](https://github.com/leonapivato/ai-assistant/issues/1210)'s
  lane 2.5, which needs this text as its authority (ADR-0015 §5).
- **Ratified on `CONTRIBUTING.md` → "Finishing an ADR PR", which is where that
  sequence is argued rather than re-argued here.** This ADR is drafted, reviewed
  and revised as `Proposed`; its status is flipped **only once both required
  lenses return clean on one tree**, and both are re-run on the flipped tree. A
  finding arriving after a flip returns it to `Proposed` and is folded there. The
  tense above is deliberate: written prospectively, the bullet is true in both
  states the document passes through, so the ratifying commit changes the `Status`
  line and nothing else.
- **Partially supersedes:**
  [ADR-0077](0077-the-observer-proposes-beliefs-from-episodes.md)
  §3's sentence enumerating what the observation prompt's payload carries, in the
  scope of an episode's principal-participant marker. That sentence — *"The prompt
  carries the episodes' canonical `content` (ADR-0005 §1) and what the model needs
  to cite them (§5)"* — enumerates exhaustively, and
  [ADR-0156](0156-a-distilled-belief-states-its-event-time-in-its-content.md) §2
  has already replaced it once to admit each episode's `occurred_at`. §5 below
  admits a third item to the same enumeration, and so takes the same form for the
  same reason: a reader holding only ADR-0077 §3 builds the observation prompt
  **without** the marker, which §5 requires it to carry, so ADR-0070 §1's test —
  an amendment is available only where a reader acts "**identically** before and
  after" — is failed on its own terms and ADR-0070 §3's partial supersession is
  what applies. The discriminator this corpus uses is met: the replaced sentence
  is a *rule an implementer obeys* rather than an explanation of one.

  **The scope is that one sentence, and the rest of §3 is what admits the change.**
  §3's bolded ruling is *"**The payload is the batch and nothing else**"*, and
  `principal` is a field of the very `EpisodicMemory` records whose `content` §3
  already sends — and, under §2 below, a string that is *already inside that
  `content`*. So §3's four refusals stand **verbatim**: the prompt still carries no
  existing beliefs, no profile, no context facet and no plan. Everything else in §3
  is untouched — the observer's own named route, the no-fallback rule and both
  arguments for it, the on-device direction, and the outcome naming the route that
  read the episodes.

  **Three neighbouring clauses were checked and are untouched.** ADR-0077 §2's rule
  that the observer proposes `SemanticMemory`, `PreferenceMemory` and
  `ProceduralMemory` and **never** `EpisodicMemory` stands, and §3 below leans on
  it. ADR-0077 §2's utility bar is neither widened nor narrowed: knowing which
  speaker is the user changes *whose* beliefs a proposal is about, never *whether*
  the bar admits one — and that holds for the bar in whichever form governs the
  episode in hand.
  [ADR-0162](0162-what-the-user-tells-the-assistant-is-recorded-and-selectivity-moves-to-retrieval-and-forgetting.md)
  §1 replaced it for an episode recording what the user told the assistant, and its
  §2 keeps it in force verbatim for one a reader ingested or a sensor captured —
  which is the class this ADR is about, so the bar this ADR leaves alone is the one
  ADR-0077 states. ADR-0077 §5's "Confidence is computed by the producer, and
  never taken from the model" is a rule about a field this ADR does not touch, and
  §3 below takes no field value from a model either.

  **ADR-0156 is not amended and nothing in it is replaced.** Its §2 first clause
  obliges the prompt to state each episode's `occurred_at`; §5 below adds an
  obligation beside it and lifts none of it. Its §2 fourth clause — a temporal
  anchor never widens what may be proposed — has an exact analogue in §5's own
  closing clause, stated there rather than borrowed.

  **The `Status` line accumulates a fourth pair rather than being replaced**
  (ADR-0070 §4): the ADR-0084, ADR-0156 and ADR-0162 pairs are kept and
  `and ADR-0163 (…)` is added on the same physical line, because replacing the whole
  value would lose the earlier dead scope. The scope names a clause and carries no
  `ADR-NNNN` token, so §4's extraction invariant — every `ADR-NNNN` after the leading
  token is a target — still holds, and all four targets are real. ADR-0077's `Status` line and dated
  note land **in this same change**, with the `Proposed` commits and not deferred to
  the flip: that is the existence condition ADR-0083 §15 states — "the naming ADR
  ships in the same change, not that it has ratified" — and it is where the note is
  reviewable, since what it states (which clause is replaced, what survives) is the
  same substantive determination this bullet makes.
- Refs: [#1210](https://github.com/leonapivato/ai-assistant/issues/1210) (the batch
  and the owner ruling), [#1162](https://github.com/leonapivato/ai-assistant/issues/1162)
  (the shape this ADR rules, narrowed rather than closed — §8),
  [#691](https://github.com/leonapivato/ai-assistant/issues/691) (person identity,
  enrolment and speaker identification, untouched — §8),
  [#1029](https://github.com/leonapivato/ai-assistant/issues/1029) (the pilot
  measurements §Context reads).

## Context

### The observer knows who the user is, and nothing anywhere states it

Every belief this system holds is a belief **about the user**, and the producer
that writes them is told so structurally rather than in words. ADR-0077 §3 keeps
the observation prompt minimal in terms — "**The payload is the batch and nothing
else**", no profile, no beliefs, no context facet — and ADR-0077 §2's bar ("the
belief is **about the user** and would change a later answer") is applied by a
model that is never told which speaker that is. It does not need to be told,
because of what the episodes are: ADR-0074 §3 rules that every turn the engine
hands back is exactly one `EpisodicMemory`, so an episode is an exchange with two
parties, and "the user" is whoever occupies the user half.

The tree states the premise where it is load-bearing and nowhere else.
`ConversationRecorder._episode` leaves `participants` empty and says why —
"``participants`` stays empty, because the two parties to a turn are structural
rather than informative and constants there would occupy, with noise, the field an
observer means to fill with the people an episode is *about*". That is a correct
decision about a turn, and it is the sentence that runs out when an episode is not
a turn.

### ADR-0074 §3 already admits the episode that breaks the premise

The premise is not a law of the corpus; ADR-0074 §3 is explicit that it is a fact
about one producer. "**The entailment runs one way: every turn is an episode, and
not every episode is a turn.**" `EpisodicMemory` is ADR-0005 §1's general kind —
"something that happened" — and ADR-0074 §3 names sensor-ingested episodes and
"a captured moment with a timestamp and no dialogue around it" as ordinary
instances. It goes further: because conversation membership lives in the
conversation index rather than on the record, "an episode belonging to no
conversation is therefore the *default* shape rather than a permitted exception".

ADR-0094 is the decision that eventually delivers those. Its §6 puts detection at
the edge and distillation at the hub; its §3 makes the spoke the thing that
releases what leaves the edge. The sensor profile's characteristic episode is
several people talking, one of whom is the user, with no user half of an exchange
with the assistant at all. On that episode the structural premise is not merely
unstated — it is **false**, and a producer applying ADR-0077 §2's bar has no way to
know it.

### It is not hypothetical, and it has been measured twice

[#1162](https://github.com/leonapivato/ai-assistant/issues/1162) records the first
benchmark pilot measuring this by accident. LoCoMo is two named third parties
chatting; the harness maps `speaker_a` onto the user half and keeps the speaker
names in the text, because the questions name people and the names are evidence
(`benchmarks/memory/corpora/locomo.py` renders each utterance as
`f"{speaker}: {said}"`). The result was **ingestion recall 56.7%** — gold evidence
cited by no belief record for 43% of answerable questions — against **82%** on
LongMemEval, first-person user↔assistant chat that matches the premise, on the same
pipeline. #1162's own reading is the one this ADR adopts: "the observer is not
failing at its job", it is "correctly executing its first-person contract on data
that violates the contract's premise".

**This ADR is not motivated by that score, and #1162 excludes such a motive by
name** ("Any change motivated by LoCoMo's score" is out of scope there). Pilot 4
(#1029, batch #1190) moved the numbers substantially and did not move the premise:
what is wrong is that a contract's premise is carried by the shape of the data
instead of by the data, so it cannot be checked, cannot be stated to the producer,
and fails silently when a new producer arrives. The measurement is evidence that
the failure is silent, not the reason to fix it.

### The owner ruled the producer; the shape is what is left

Owner ruling of 2026-08-17, recorded on #1210: *"the product should know which
speaker is the user; this is the responsibility of a spoke/client to provide."*
That settles **who supplies** the answer and rules out the obvious alternative — a
hub-side inference over content. What remains to decide is the field's shape, what
it may say, who may read it, what its absence means, and what it deliberately does
not settle.

### Three facts about the tree that make this a decision rather than a one-line change

1. **`EpisodicMemory.participants` is reserved and empty by construction.** The
   recorder's docstring quoted above reserves it for the people an episode is
   *about*, and ADR-0078 §7 pins its ordering into `proposal_fingerprint` —
   "``EpisodicMemory.participants`` is that case and keeps its order". A marker
   expressed as an index into `participants` would need that tuple populated by a
   producer that is ruled not to populate it, and would make an epistemic claim
   ("these are the people") in order to make a structural one.
2. **`about_person` is a different axis and cannot carry this.** ADR-0100 makes it
   the *subject* axis — whom a belief is **about** — and rules that `None` "means no
   subject is stated, and is read as the owner's", with "**The owner is never named
   here**". A field whose entire discipline is that the owner is spelled by an
   absence cannot also be the field that names the owner.
3. **The one producer that can set a marker today needs no Protocol change.** The
   benchmark harness drives the real capture path directly —
   `benchmarks/memory/ingest.py` calls `harness.lifecycle.capture(...)` — and
   `ConversationLifecycle` is an `orchestration` class, not a `core` Protocol. So
   the sensor submission surface can stay deferred (ADR-0094 §10) while this
   decision is still testable end to end, and the contract surface this ADR opens
   is one field rather than a seam.

## Decision

### 1. An episode may name which of its participants is the user, in one optional field

> **Normative.** `EpisodicMemory` grows one field,
> `principal: NonBlankEncodableText | None`, defaulting to `None`. Stated, it names
> the speaker — among those this episode records — who is the owner of this hub.

> **Normative.** No other memory kind grows this field, and no other type does.
> Only an episode records who spoke.

**A field, because the premise has to be checkable.** The alternative available
without one is a convention inside `content` — a producer prefixing "the user is
Caroline" to the text. That puts a structural claim inside the region a model is
entitled to read as the episode's own words, which is exactly what ADR-0098 §2's
non-forgeability rule exists to prevent, and it makes the claim invisible to every
reader that is not a model. A field can be rendered non-forgeably (§5), can be
absent in a way whose reading is ruled rather than guessed (§4), and can be
forbidden to influence anything else (§6). A convention can do none of the three.

**`principal`, not `participants[0]` and not `about_person`,** for the two reasons
§Context states as facts about the tree. The name is chosen for the question it
answers — *which participant is the principal one* — and is deliberately read
against the neighbouring `participants`.

> **Normative.** `principal` is not a security principal, an account, a subject of
> authorisation, or an input to any permission or grant decision. Nothing in
> `permissions/` or in ADR-0097's grant path reads it.

That clause exists because the word carries a second meaning in this corpus's
neighbourhood and a later reader could import it. The field says which voice in one
recording belongs to the hub's owner. It authorises nothing.

### 2. The value is a tag the episode's own `content` uses, it is owed where it is stateable, and it resolves to nothing

> **Normative.** A producer sets `principal` only to a speaker tag the episode's own
> `content` already uses for that speaker, byte for byte.

> **Normative.** Where a producer renders `content` in which the speakers are
> distinguishable and knows which of them is the owner, it renders a tag for that
> speaker and states it as `principal`. The marker is not optional for such a
> producer: the field's optionality exists for the turn, whose principal is
> structural (§3), and for an episode that records no distinguishable speakers at
> all.

> **Normative.** `principal` resolves to nothing beyond the record that carries it.
> Nothing matches two records' markers, normalises, case-folds, aliases, strips or
> de-duplicates one, or joins one to `about_person`, to a `participants` entry, to a
> grant, to a spoke profile, to a conversation, or to any registry. Two equal
> markers are not thereby one speaker, and two unequal ones are not thereby two
> speakers.

> **Normative.** Nothing validates `principal` against `content`. The first clause
> is an obligation on producers; it is not a construction-time check, and no
> validator is added for it.

**The first clause is what keeps minimisation intact, and it is the load-bearing
one.** ADR-0004 §7's rule is the one ADR-0077 §3 and ADR-0156 §2 both answer to,
and the answer here is the same shape ADR-0156's was: the marker adds no datum to
any payload, because the string it holds is *already in the `content` that payload
carries*. What the prompt gains is a **pointer into text it already had**, and a
pointer to a string cannot disclose more than the string. A marker free to hold any
value would be a genuinely new class of data — a name the producer knows and the
episode does not record — and would have to be argued as one. This clause refuses
that outright and is why the argument is not needed.

**The second clause is what stops the first from becoming a loophole**, and the
pair is best read as a partition of the producer's situation:

- **Speakers distinguishable, owner known.** The marker is *owed*, and the tag it
  names is one the producer is putting into `content` anyway. This is the whole
  case this ADR is for.
- **Speakers distinguishable, owner not known.** No marker is stateable, and none
  may be guessed (§3). This is diarization and identity — #691's, not this ADR's
  (§8) — and §3's producer clauses record that no producer this ADR admits can
  reach the state.
- **Speakers not distinguishable.** There is no tag for a marker to name and
  nothing a marker could fix: undifferentiated transcript text is a capture-quality
  question, and a field naming a speaker cannot answer it.

Without the second clause a producer could render a tagged transcript, know
perfectly well which speaker is the owner, and state nothing — leaving the episode
in the second row by choice rather than by limitation. The clause closes that, and
it is stated as a producer obligation rather than a check, for the fourth clause's
reason.

**The third clause answers the objection this ADR most has to answer.** ADR-0100
§3 states that "there is no user identity anywhere in this system", and a field
naming the user looks like one. It is not, and the difference is the same one
ADR-0100 §6 draws for `about_person`: "**A label, resolving to nothing** … Not an
identifier, not a key, not a reference." This ADR applies that discipline at a
*narrower* scope than ADR-0100 does — one record rather than the corpus — because a
speaker tag is meaningful only inside the recording that used it. Nothing
accumulates: a hundred episodes carrying `"Caroline"` do not thereby know a
Caroline, are not thereby joinable, and give no surface a person to enumerate. What
would create an identity is a join, and the clause forbids every join by name.

**The fourth clause is a refusal with a precedent.** A validator asserting the tag
occurs in `content` would be cheap to write and wrong twice over: it would decide a
matching rule — substring? prefix? case-sensitive? — that belongs to no ADR, and it
would fail records whose rendering places the tag somewhere a naive scan misses,
turning a correct capture into a construction error. ADR-0106 §7 closed the window
on a validator in a closely analogous place, and ADR-0100 §6's "stored and returned
byte for byte: nothing normalises, case-folds, aliases or de-duplicates it" is the
same instinct: a label is carried, not policed. The only check the type makes is
the one `NonBlankEncodableText` already makes — a marker that is stated is not
blank, because a producer saying `""` meant to speak and said nothing.

### 3. The capturing client supplies it, and nothing at the hub infers one

> **Normative.** `principal` is set only by the component that captured the episode,
> from what its own capture gave it. No component derives one from an episode's
> `content`, from a model, from `participants`, from `about_person`, or from any
> other record — at capture, at ingest, at retrieval, at render, or in a migration.

> **Normative.** The observer sets none. It proposes no `EpisodicMemory` at all
> (ADR-0077 §2), and this ADR does not lift that.

> **Normative.** The conversation capture path (ADR-0074 §3) sets none. A turn
> between the owner and the assistant states its principal structurally, and a
> marker there would be a constant.

**This is the owner's ruling given its mechanism, and ADR-0094 is why it is the
right one.** §6 of that ADR puts detection at the edge and distillation at the hub;
§3 makes the spoke the thing that releases what leaves the edge. Diarization — the
work of deciding which utterance belongs to which speaker, and which speaker is the
person holding the device — is edge work by that split, done where the microphone,
the enrolment and the device are. A hub-side inference over transcript text would
be a model guessing at the one fact the whole belief store is oriented around, and
guessing it *silently*: there is no confidence to attach, no provenance to record,
and no user act to point at when it is wrong.

**The third clause keeps the field honest in the common case.** Every episode in
production today is a turn, and stamping a constant marker on all of them would put
noise in the field for no reader — the same argument the recorder already makes for
`participants`, applied to the field beside it. §4's fourth clause is what makes
the omission correct rather than merely economical.

**The seam is a keyword on capture, and it is not contract surface.**
`ConversationLifecycle.capture` grows an optional keyword-only parameter defaulting
to `None`, threaded to the `EpisodicMemory` it builds. `ConversationLifecycle` is an
`orchestration` class; the engine's own `_capture`, which serves `converse` and
`resume`, passes nothing and so continues to satisfy the clause above. No `Engine`
Protocol method changes, and the sensor submission surface by which a spoke would
deliver a multi-party episode stays exactly as deferred as ADR-0094 §10 left it
(§8).

> **Normative.** The benchmark harness, which drives capture directly as a client,
> sets `principal` on episodes it captures from a corpus whose speakers are named
> third parties, to the same tag its own rendering prefixes to those utterances. It
> sets none for a first-person corpus, whose episodes satisfy the structural
> premise unchanged.

That clause is here rather than in an implementation brief because it is the only
part of this decision that is exercisable today, and because it is what makes the
decision falsifiable: LoCoMo is the measured case where the premise is false, and a
harness that captures those episodes without a marker leaves the ADR untested. §7
carries the pre-registration obligation that goes with changing a measured
pipeline.

> **Normative.** This ADR admits exactly two producers of episodes: the conversation
> capture path, which records turns and states no marker, and a client driving that
> path directly, which states one where §2's second clause obliges it. It admits no
> producer that can deliver an episode recording several distinguishable speakers
> without a marker.

> **Normative.** A later decision that admits such a producer — the sensor
> submission surface ADR-0094 §10 defers — rules at that time whether an episode
> recording distinguishable speakers with no marker is eligible to be observed at
> all. This ADR neither grants nor denies that eligibility; §4's protection of an
> absent marker does not decide it, and §6's second clause is the one carve-out in
> this ADR's prohibitions that leaves the ruling available.

**These two clauses are the honest statement of this ADR's reach, and they are
worth stating rather than leaving to be inferred.** The state a reviewer will reach
for — a multi-party episode arriving at the observer with no marker, so that the
producer must again guess whose beliefs it is writing from the same ambiguous text
— is *unreachable under the producers named above*: a turn has no ambiguity to
resolve, and a client capturing named speakers owes the marker under §2. It becomes
reachable the day a spoke can submit a captured conversation, and that is the day
the eligibility question has both a producer to attach to and evidence about how
often diarization actually fails. Deciding it now would be ratifying a
withholding rule against a producer whose failure modes nobody has seen.

### 4. Absence says no marker was stated, and says nothing else

> **Normative.** `principal` absent means no marker was stated. It is not
> "unknown"; it is not an assertion that the owner is among the speakers this
> episode records; and it is not an assertion that they are not.

> **Normative.** No reader, renderer, store, policy or surface may withhold,
> downrank, exclude, degrade or retain differently an episode on the ground that it
> states no `principal`, nor infer a principal for one (§3).

> **Normative.** The clause above binds retrieval, ranking, rendering, retention and
> the write gate. It does **not** reach the question of which episodes are eligible
> to be observed at all, which §3's last clause leaves to the decision that admits a
> producer able to raise it.

> **Normative.** Where an episode is a conversation turn (ADR-0074 §3), an absent
> marker leaves that producer's structural premise exactly as it stands: the
> exchange's user half is the owner. That reading is a fact about the capture path
> and about the shape of what it records, not a meaning of this field, and no
> reader may extend it to an episode from another producer.

**The fourth clause is separated from the first deliberately, and the separation is
the whole of this section.** The tempting shorter rule — *absent means the episode
is an owner↔assistant exchange* — is false about the kind, and ADR-0074 §3 says so
in the same breath it establishes the premise: "**the entailment runs one way:
every turn is an episode, and not every episode is a turn**", and it names a
calendar event and "a captured moment with a timestamp and no dialogue around it"
as ordinary instances. Neither has a speaker at all, so neither can carry a marker,
and a rule reading their absence as a two-party exchange would attribute a
conversation to a record of a meeting invitation. The premise belongs to the
producer that satisfies it; the field merely declines to restate it.

**Two states, never three** — the shape ADR-0100 §1 fixed for `about_person`, taken
here for the same reason. A third state ("unknown") would have to be produced by
someone, and §3 forbids the only component that could produce it from inferring
anything; what a reader needs instead is the first clause's refusal to read
anything into the silence.

**Backwards compatibility is free, and the store is why.** `SqliteMemoryStore`
records that "**The blob stays the truth and the column is a derived index** …
every read decodes the record from ``data``", so a record written before this field
existed decodes with the default and states no marker — which is exactly right for
it, since every episode written before this field existed is a turn (§3) and the
fourth clause reads it as one. **No migration, no backfill and no column are owed**,
and none may be added: `about_person` has a nullable column because ADR-0101 gives
it a predicate to sit under, and §6 below gives `principal` none.

### 5. It travels with the content, to a model, non-forgeably

> **Normative.** A surface that renders an episode's `content` to a model renders
> that episode's `principal` alongside it where one is stated, saying that the
> speaker so named is the owner. Where none is stated it renders nothing in its
> place — no placeholder, no "unknown", no default.

> **Normative.** The marker is rendered in the same system-supplied region the
> episode's other rendered fields occupy, and never inside the region a model may
> read as the episode's own text (ADR-0098 §2, ADR-0072 §6).

> **Normative.** The clauses above bind the observation prompt (ADR-0077 §3 as
> partially superseded by ADR-0156 and by this ADR) and the planner's record
> renderer, which is what carries ADR-0158 §4's episodic supplement into the
> answering prompt. They bind no user-facing surface, which may render the marker
> or not.

> **Normative.** A principal marker never widens what may be proposed. ADR-0077
> §2's bar — the belief is about the user and would change a later answer, and the
> exchange is not summarised — is applied unchanged, and the presence of a marker is
> not a reason to propose a belief that bar would otherwise refuse.

**Content and marker travel together because separating them is the failure.** The
harm this ADR exists to prevent is a producer reading `"Melanie: I finally booked
the trip"` in an episode whose owner is Caroline and writing a belief about the
owner's trip. That harm is caused by rendering the content; it is prevented by
rendering the marker with it. A rule permitting one surface to render the content
alone would leave exactly one path by which the misattribution still happens, and it
would be the quiet one — nothing reports which surface rendered what.

**Both bound surfaces are ones where the misattribution is live.** The observation
prompt is where beliefs are minted, so it is the obvious one. The planner's renderer
is the less obvious and not the lesser: ADR-0158 §4 admits an episodic supplement
retrieved by relevance from other conversations, and an episode from a captured
multi-party conversation arriving in an answering prompt without its marker tells
the answering model that the interlocutor's words are the user's. ADR-0074 §5's
continuity tail is unaffected in practice, because its episodes are turns and state
no marker (§3) — the clause covers it anyway, because "which records are turns" is
not something a renderer should have to know.

**Minimisation is satisfied rather than strained**, and the argument is §2's first
clause rather than a fresh one: the marker is a string already inside the `content`
the prompt carries, so ADR-0077 §3's four refusals stand verbatim — no existing
beliefs, no profile, no context facet, no plan. De-duplication remains the gate's
job, and the store ids stay out of the prompt for the reason `learning/observer.py`
already gives: "the model has no use for an id it is not allowed to cite".

**The fourth clause holds a line a reviewer should test**, and it is ADR-0156 §2's
fourth clause stated for this field rather than borrowed from it. The measured
ingestion loss is large and the temptation is to let this ADR buy some of it back by
admitting third-person beliefs the utility bar refuses. It does not. What the marker
changes is *whose* beliefs the observer is entitled to think it is writing; what may
be believed at all is untouched, and a belief about the interlocutor is admitted or
refused by exactly the rules that admitted or refused it before — ADR-0077 §2's bar
as ADR-0162 §2 leaves it standing for a captured episode, and ADR-0100's
`about_person` discipline for a belief about someone else in the user's world.

### 6. What it may not influence

> **Normative.** `principal` is never an input to retrieval, ranking, read
> eligibility, band assignment, deduplication, conflict detection, retention, expiry
> or policy. No `MemoryStore` read filters or orders on it, no `MemoryPolicy` rules
> on it, and no producer's band or confidence is computed from it.

> **Normative.** One exception exists, and it is the one §3's last clause defers: a
> decision admitting a producer that can deliver an episode recording
> distinguishable speakers with no marker may rule such an episode ineligible to be
> **observed**. That ruling is available to that decision and to no other, it reads
> the marker's *absence* and never a marker's value, and it changes nothing in the
> enumeration above — an episode ruled out of an observation batch is retrieved,
> ranked, retained and rendered exactly as before.

> **Normative.** `participants` and `about_person` are unchanged in shape and in
> meaning. `principal` is not written into `participants`, is not read from it, does
> not populate `about_person`, and is not read as a subject.

**Nothing here is a capability being withheld; it is a field being kept to one job.**
Each of the listed inputs is a place where a later lane could reach for the marker
because it is conveniently present, and each would turn a rendering aid into an
epistemic instrument that §2's third clause has just refused to give it standing
for. A retrieval filter on `principal` would be the join §2 forbids, wearing a
predicate.

**The exception is drawn narrowly, and the two halves of the drawing matter
separately.** *Absence, never value*: a rule reading which speaker a marker names in
order to decide what to observe would be the epistemic instrument the paragraph
above refuses, while a rule noticing that a producer said nothing is reading the
producer's own admission of what it does not know. *Observation, never retrieval*:
the observer is the one consumer that forms beliefs about the owner from the text
it is shown, so it is the only place where not knowing who the owner is could
warrant declining to read at all; everywhere else the episode is being served back
to the person it belongs to, and the marker's absence is none of that reader's
business (§4). This ADR grants the exception rather than exercising it — nothing
today may act on it, because §3 admits no producer that can reach the state.

**One mechanical consequence is worth stating rather than discovering.**
`MemoryUpdateProposal._fingerprint_projection` is built from `model_dump` with a
*denylist* — `_FINGERPRINT_EXCLUDED_RECORD_FIELDS` holds `id` and `score` — so a new
field is included by default. This ADR **adds no exclusion**: the marker is part of
what an episode says, and two episodes differing only in it are not the same
proposal. The change is inert in practice, because no producer proposes an
`EpisodicMemory` at all — the observer is forbidden to (ADR-0077 §2) and capture
writes its episode directly rather than through `MemoryWriter.ingest` (ADR-0075 §2)
— so no fingerprint in the system changes value. Stating it here is what stops a
later reader from "fixing" the projection in either direction without an ADR.

### 7. What the implementing lane owes, and what it may not touch

The lane is #1210's 2.5. It owes, and owes nothing beyond:

- The field on `EpisodicMemory` in `src/ai_assistant/core/types.py`, with a
  docstring carrying §2's discipline and §4's reading of absence — the
  form `about_person`'s docstring already takes for ADR-0100's clauses.
- The keyword on `ConversationLifecycle.capture`, defaulting to `None`, threaded
  into the `EpisodicMemory` it builds, with the recorder's docstring stating that
  the engine's own capture path passes none and why (§3).
- The observation prompt's rendering, in `learning/observer.py`'s batch renderer,
  beside the localised instant ADR-0156 §2 put there — and the batch renderer's
  docstring updated, since it currently states the payload enumeration in terms
  ("**The payload is the batch and nothing else**  … each episode's canonical
  ``content`` …, the label the model cites it by, and — since ADR-0156 §2 — that
  episode's own ``occurred_at``").
- The planner's record renderer, non-forgeably (§5). **This lane lands after
  #1210's lane 2.1**, which is rewriting that same renderer for #1194;
  taking the two in the other order would put two lanes in one file.
- The harness, per §3's harness clause: LoCoMo's `speaker_a`, matching the tag
  `benchmarks/memory/corpora/locomo.py` already prefixes to each utterance;
  nothing for LongMemEval.
- Tests: a record written without the field decoding from a stored blob and
  reading as absent (§4); a marker surviving the store round trip byte for byte
  (§2); both renderers with and without a marker, including that nothing is
  rendered in its place when absent (§5); and the non-forgeability of the rendered
  region (§5).

It may not: add a validator (§2), add a store column, migration or backfill (§4),
add a `Settings` field, add or change any Protocol member, populate `participants`
or `about_person` from the marker (§6), or change the observer's utility bar (§5).

> **Normative.** Changing what the harness captures changes a measured pipeline, so
> the harness half of this lane is pre-registered as its own arm on
> [#1029](https://github.com/leonapivato/ai-assistant/issues/1029) before it is
> scored, stating the expected direction. A run that mixes it with an unrelated
> change measures neither.

### 8. What this ADR does not decide

- **What names a person, how one is enrolled, and how an utterance is attributed to
  a speaker.** That is diarization and identity, it is #691's, and this ADR adds no
  tenth ADR reference pointing there by deciding any of it. §2's third clause is
  precisely the boundary: this decision consumes a label a client already computed
  and refuses to give it any meaning outside its record.
- **Whether two markers in different episodes denote the same speaker.** §2 forbids
  the join and does not replace it with an answer. The instrument that could lift
  that is ADR-0101's, as ADR-0100 §6 already rules for `about_person`.
- **Multi-user hubs, or whose hub this is.** ADR-0099 §2 rules the subject axis
  orthogonal to that question and this ADR takes it no further.
- **The ADR-0106 §6 taint boundary for a captured multi-party conversation** —
  whether an interlocutor's utterance is recorded external content while the
  owner's own words in the same episode are first-party. #1162 raises it and it
  **stays open there**. This ADR is deliberately silent: the marker says who the
  owner is and says nothing about the standing of anyone else's words, and deciding
  the taint boundary would be deciding what `derived_from_external` means for a new
  source class — a decision with its own enforcement point and its own review set.
  **This is what narrows #1162 rather than closing it** (see below).
- **The sensor submission surface** by which a spoke delivers a captured episode to
  the hub. ADR-0094 §10 defers it and this ADR does not open it; §3's seam is the
  existing capture path, which is why a docs-only decision is testable today.
- **Whether an episode recording distinguishable speakers with no marker is
  eligible to be observed at all.** §3's last clause defers it with the producer
  that first makes it reachable, and §4's third clause keeps the absence rule from
  pre-empting it. No producer this ADR admits can create that episode, so the
  deferral costs nothing today and the decision, when it is taken, will have a
  producer's measured failure rate to take it against.
- **How an episode says positively that the owner is *not* among its speakers** — a
  room the user is not in. §4's first clause makes absence say nothing either way,
  so no such episode is misdescribed today; what is deferred is a way to state the
  fact affirmatively, and the condition that fires it is a producer that can tell
  the difference and needs the distinction acted on. Answering it now would be
  ratifying a third state on the strength of no producer's need.
- **Whether user-facing surfaces render the marker** (§5's third clause leaves them
  free), and whether more than one participant may be marked.

**#1162 is narrowed, not closed.** It carries two questions: speaker attribution as
episode metadata, and the ADR-0106 §6 boundary for third-party utterances in a
captured conversation. This ADR rules the first — the shape #1162 sketches, "a
label, not a name … the observer still receives no profile data" — and leaves the
second open on that issue, with the paragraph above as the reason. The implementing
lane updates #1162 to say so rather than closing it.

## Consequences

- **The premise the belief store is built on becomes a fact in the data rather than
  a property of one producer.** A new capture source can state it; a reader can
  check it; a renderer can carry it. The failure mode this replaces is silent by
  construction, which is what made it worth a decision at a moment when no
  multi-party producer exists yet.
- **The LoCoMo arm becomes an honest measurement instead of a known-invalid one.**
  #1162 records the harness's first-person mapping as a validity limitation; with
  §3's harness clause the corpus is captured as what it is. Whether the score moves is
  a measurement, pre-registered under §7, and this ADR predicts nothing about it.
- **`EpisodicMemory` gains a third participant-shaped field**, and three is where a
  reader starts needing to be told which is which. §6's third clause and the
  docstring §7 requires are the mitigation; the alternative — folding them — is
  refused below.
- **A rendering obligation now spans two subsystems** (`learning` and `planning`),
  and a third renderer added later must honour it. §5's first clause is stated over
  "a surface that renders an episode's `content` to a model" rather than over the
  two known sites, so a new one inherits the rule instead of being forgotten by it.
- **What would trigger revisiting this.** A producer that needs to mark more than
  one participant, or to record an episode with no owner in it; a decision that
  gives labels cross-record meaning (#691), which would make §2's third clause the
  thing standing in the way rather than the thing protecting the design; or a
  measured finding that stating the marker changes *what* the observer proposes
  rather than *whom* it proposes it about, which §5's fourth clause forbids and
  which would mean the clause needs an enforcement point rather than a statement.

## Alternatives considered

- **An index into `participants`.** Refused for the two reasons §Context states:
  the recorder is ruled not to populate that tuple, so the marker would be
  unexpressible without first making a claim about who the people are; and
  ADR-0078 §7 pins the tuple's order into `proposal_fingerprint`, so an index would
  be a value whose meaning depends on a canonicalisation rule decided for a
  different purpose. Indices also survive serialisation badly — a filtered or
  re-derived tuple silently re-points the marker at another person, which is the
  one failure mode worse than having no marker.
- **Reuse `about_person`.** Refused: ADR-0100 §3 rules that "**The owner is never
  named here**" and that `None` is read as the owner's, so the field's entire
  discipline is that the owner is spelled by an absence. Overloading it would make
  a record naming the owner mean the opposite of a record not naming them, in the
  same field.
- **A structured `Participant` type with an `is_principal` flag, replacing
  `participants`.** Refused as disproportionate: it changes the type of a ratified
  field, breaks every reader and every stored blob, forces a migration §4 shows is
  otherwise unnecessary, and buys a shape nothing has asked for — the *people an
  episode is about* and the *speaker who is the owner* are different questions, and
  the pilot needs only the second.
- **A boolean `multi_party`, leaving attribution to the model.** Refused: it tells
  the producer that its premise is false without telling it what is true, which
  converts a silent misattribution into a licensed guess. The observer would have to
  infer the owner from content — exactly what §3 forbids, arrived at by a field
  instead of by a line of code.
- **A prompt convention: prefix "the user is Caroline" to the episode's text.**
  Refused twice over. It puts a system claim inside the region a model may read as
  the episode's own words (ADR-0098 §2), and it is invisible to every non-model
  reader, so nothing can render it, filter on its absence, or test it.
- **A `Settings` value naming the owner's speaker tag.** Refused: it is per-episode
  data modelled as per-deployment configuration, so it is wrong the moment two
  captures use different tags — and it would make the owner's name a value the
  operator types into a config file, which is the identity ADR-0100 §3 says this
  system does not have.
- **Decide the ADR-0106 §6 taint boundary here as well.** Refused as scope: it is a
  different decision, with a different enforcement point (the gate) and a different
  blast radius (every `DERIVED` proposal resting on a sensed source), and folding it
  in would make a one-field decision into a leg. It stays on #1162 (§8).
