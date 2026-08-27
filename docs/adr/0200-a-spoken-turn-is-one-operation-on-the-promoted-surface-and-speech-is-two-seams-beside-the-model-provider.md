# 200. A spoken turn is one operation on the promoted surface, and speech is two seams beside the model provider

- Status: Proposed
- Date: 2026-08-27
- **Durability clause.** Every quotation below — from an ADR, from
  `core/protocols.py`, from `core/types.py`, from `core/config.py`, from
  `wire/`, from `interfaces/gateway/`, from `models/`, or from an issue — is of
  its text as it stood at this ADR's base, `5510efe8`, not of its text on any
  later day, **except ADR-0199**, which merged and was ratified after that base
  and is quoted as it stands at `62724fe1`. Every other ADR this decision
  composes with reads `Accepted` at both. Where a later ADR changes one of the
  ADRs cited, this ADR
  is read against the text quoted here and that ADR's own record says what
  moved. This is ADR-0143's clause, taken for its reason.

## Context

### The question, and what it is worth

`track:voice` (#1318) milestone 19 — *talk to it* — has one exit test: the owner
holds push-to-talk in a browser on another device, asks aloud about their own
life, hears an answer drawn from accumulated memory, and a class ruled
unspeakable is deflected rather than read aloud. Batch #1657 cuts that milestone
into two decisions and a roadmap transcription. ADR-0199 is the disclosure half
— what may be spoken. This is the mechanism half: how the owner's voice reaches
the hub, where the composition of speech-to-text, turn, and text-to-speech
lives, what contracts it needs, and what the answer travels back as.

It decides no implementation. Every Protocol it names ships as a triad in a
later lane, and §13 is the work order those lanes are briefed against.

### The state of the tree, read rather than remembered

Each of these was read at this ADR's base, `5510efe8`.

- **There is no audio path anywhere.** No `core` type carries audio, no
  Protocol transcribes or synthesises, no setting bounds a recording, and no
  gateway route accepts one. `grep` over `src/` for audio, microphone or speech
  returns nothing but ADR prose. This is a greenfield seam, not an extension.
- **`AssistantEngine` has two turn calls**, `converse` and
  `converse_streaming`, and no member named `ask`. `/ask` and `/ask/stream` are
  *gateway paths* (`interfaces/gateway/server.py`, `_ASK_PATH` and
  `_ASK_STREAM_PATH`), mapped onto those two methods by `_ASSISTANT_PATHS`.
- **The wire's canonical encoding carries no `bytes`.** `wire/codec.py`'s
  `project` is a total dispatch over the value space with no `bytes` branch; its
  fallthrough raises `TypeError`, and its docstring states the posture — "a type
  nobody has spelled a form for has no canonical bytes, and guessing one would be
  the divergence this module exists to prevent". ADR-0087 §2c's scalar table has
  no `bytes` row. It does dispatch `BaseModel` through `model_dump()` and `str`
  through `encodable_text`.
- **The wire surface is derived, not transcribed.** `wire/surface.py` reads
  `METHODS`, every argument adapter and every result adapter off
  `AssistantEngine`'s own annotations: "a method the Protocol grows is a method
  this module already knows about, and one whose type the wire cannot carry
  fails loudly at import rather than silently at the first call."
- **The gateway is HTTP with no socket, and cannot take a chunked upload.**
  ADR-0175 §1: "The gateway serves no WebSocket, offers no protocol upgrade and
  honours no `Upgrade` header, and serves nothing a browser reaches with
  `EventSource`." `interfaces/gateway/http.py`'s `_content_length` refuses
  `Transfer-Encoding` outright — "a chunked body is a second framing, and
  ADR-0168 §8's cap has to bound whatever framing arrives" — so a browser
  request is one `Content-Length`-declared body, read incrementally against
  `gateway_max_request_bytes`.
- **Three byte bounds already exist and none of them is about audio.**
  `hub_max_frame_bytes` (ADR-0084 §3) defaults to 16 MiB and bounds a frame,
  envelope and payload together; the contract limit is that figure less
  ADR-0085 §8b's 512-byte envelope reserve, applied by §8c to "the whole
  serialised payload… measured as the byte length of that payload's canonical
  UTF-8 JSON encoding"; `gateway_max_request_bytes` (ADR-0168 §8) defaults to
  1 MiB and bounds "request line, headers and body together, not the body
  alone". `core/config.py` holds no setting whose subject is a recording.
- **The embedding seam is the tree's only blocking-inference precedent, and it
  runs in this process.** `models/_embed_worker.py` spawns
  `threading.Thread(..., daemon=True)`, not a process: "the work runs on a
  **daemon thread the embedder owns**, never on the event loop's default
  executor". The deadline is a separate decorator, `models/bounded_embedder.py`,
  because ADR-0118 §2 puts it "on the decorating `Embedder` the composition root
  wires, so that it composes over *every* implementation rather than binding
  this one".
- **Routing and retry exist over `ModelProvider` and nothing else.**
  `models/__init__.py`'s `__all__` carries `RetryingProvider`, `Route` and
  `RoutingProvider`; there is no `RoutingEmbedder` and no `RetryingEmbedder`.
- **`PROTOCOL_VERSION` is 17** (`wire/envelope.py`), and its comment records
  ADR-0124 §9 as the rule that moves it: the rule reaches "any change to the
  promoted surface's method set", and "adding a method bumps, and that is the
  honest consequence rather than an oversight".

### Four premises of the dispatching brief, checked and corrected

The brief for this lane, and #1318's own milestone-19 line, carry four claims
that do not survive contact with the corpus. Each is corrected here rather than
carried forward, because each would have shaped the decision.

1. **"STT/TTS behind ADR-0013's router" cannot be satisfied literally.**
   ADR-0013's subject is `ModelProvider` throughout: §2's `Route` is "(a
   provider, an optional per-route `"provider:model"` override)", §4 names
   `ModelProvider.complete`, §6 has `RoutingProvider` receiving "fully-constructed
   `ModelProvider`s by injection", and §1 says "no Protocol changes". Nothing in
   it obliges any other seam to route, and §3 is explicit that even the
   composition order is "a wiring decision, and `orchestration` owns it". A
   speech seam is not a `ModelProvider` (§1), so what carries over is ADR-0011's
   and ADR-0013's *wrapper shape*, available to a later decision, not a rule
   this ADR must satisfy. §11 defers it with its firing condition.
2. **"Inference in worker processes, never the hub process" is not a ratified
   clause.** The sentence is issue #1029's, and ADR-0143 cites it twice in
   *Context*, under "What already binds, and is not relitigated here" — not in
   its Decision. The only ADR-level clause is ADR-0143 §8's, whose subject is
   one Protocol: "A batch runs in the process that submits it and never in the
   hub. No `BatchCompleter` is wired into `ai_assistant.service`, and no
   scheduler job polls one." Read as a general law it would also condemn
   `FastEmbedEmbedder`, which runs ONNX inference inside the hub process today
   under ADR-0118. §5 decides what actually binds a speech implementation, and
   it is ADR-0118's two-layer containment rather than a process boundary.
3. **The gateway's HTTP-only posture is ADR-0175 §1, not PR #1331.** #1331
   implemented ADR-0168 and ADR-0172 and *flagged* HTTP-only as a lane
   consequence; ADR-0168 §12 deferred the question and left open "whether a push
   carrier such as a WebSocket is among them". The normative clause quoted above
   arrived in ADR-0175 §1.
4. **The browser leg is ADR-0174 §1's fourth boundary, not ADR-0124 §1's
   third.** ADR-0124's status line records §1's enumeration partially superseded
   by ADR-0174, which adds "the gateway's **remote browser transport** between a
   gateway and a browser on another device of the owner's overlay — its two
   halves being the gateway's remote browser listener and the front-end bundle
   this repository serves to that browser". The exit test's browser is on
   another device, so the utterance leaves it across that fourth boundary in the
   half ADR-0174 §1 says a draft would drop — our own front end. ADR-0170's
   trace of the answer's return leg (Context, "Why 'a reply is egress' is a
   misreading") predates ADR-0174 and is stale by one boundary for a browser.

### What already binds, and is not relitigated here

- **ADR-0094 §7** — "Where a spoke's submission is derived from source material
  the spoke holds, the spoke submits the source material and may not substitute
  a lossy, model-dependent derivation of it", and for an audio-shaped spoke
  "this means the promoted slice, not a transcript made at the edge".
- **ADR-0168 §1** — "The browser gateway is a spoke under ADR-0094 §1 … Every
  obligation ADR-0094 places on a spoke binds it, and this ADR grants it no
  exemption from any of them." So ADR-0094 §7 binds the gateway, and §2's rule
  below has a ratified ground independent of golden rule 3.
- **ADR-0094 §6** — a spoke "may decide **whether to send** — voice-activity
  detection, wake-phrase spotting, bounding, thresholding. It may not decide
  **what a submission means**". A push-to-talk press is exactly detection.
- **ADR-0085 §2** — the subject of a call is positional and every other
  argument keyword-only; §8b's 512-byte reserve and §8c's payload limit.
- **ADR-0124 §9** — any change to the promoted surface's method set bumps
  `PROTOCOL_VERSION`.
- **ADR-0170 §8** — a composition failure "**degrades the turn; it does not fail
  it**", because failing would throw away an answer the user already has.
- **ADR-0074 §3** — every turn the engine hands back is captured as exactly one
  `EpisodicMemory`, at the point a `TurnOutcome` is produced; §11 records that
  "**nothing on a turn records where it came from**".
- **ADR-0137 §2** — the sanctioned cut is the contract seam, and a triad rides
  with its primary production implementation.
- **ADR-0015 §5** and golden rule 5 — nothing implements against this until it
  has merged.

## Decision

We will add two sibling Protocols for speech and **one** turn call that composes
them, on the hub, in `orchestration`; carry audio across the existing wire and
the existing gateway without changing either; retain no audio; and bound a
recording with a setting of its own.

### 1. Speech is two new sibling Protocols; `ModelProvider` is not widened

> **Normative.** Speech recognition and speech synthesis are introduced as **two
> new Protocols** in `core/protocols.py`, named `SpeechTranscriber` and
> `SpeechSynthesizer`. No member is added to `ModelProvider`, no existing member
> of `ModelProvider` or of any other Protocol changes signature or clause,
> neither new Protocol inherits from another, and neither is required to be
> implemented by the same object as any other. An object may implement both;
> nothing requires that it does.

This is ADR-0143 §1's ruling and its three grounds, which hold here unchanged.
`core/protocols.py`'s own module docstring says "Prefer adding a new Protocol
over widening an existing one". ADR-0021 §3 ruled the same fork — "widening
`decide`'s parameter is breaking; adding a second Protocol beside `ActionPolicy`
is additive" — and the asymmetry is stronger for a `@runtime_checkable`
structural Protocol, where a new member on `ModelProvider` silently unsatisfies
`PydanticAIProvider`, `RetryingProvider`, `RoutingProvider` and every fake at
once. And speech is a capability most providers do not offer, which is
`Embedder`'s exact ground and `BatchCompleter`'s after it.

> **Normative.** `SpeechTranscriber` has two members and no more: a `formats`
> property answering the `SpokenAudioFormat` members this implementation can
> decode, and `async transcribe(audio: SpokenAudio) -> EncodableText`, returning
> the words it heard. A blank return is not a failure: it means the recording
> carried no words, and §4 decides what the engine does with it.

> **Normative.** `SpeechSynthesizer` has two members and no more, symmetric with
> the transcriber's: a `formats` property answering the `SpokenAudioFormat`
> members this implementation can **produce**, and
> `async synthesize(text: NonBlankEncodableText, *, format: SpokenAudioFormat) -> SpokenAudio`.

> **Normative.** The returned value's `media_type` **equals** the requested
> `format`. An implementation asked for a format its `formats` property does not
> name refuses it rather than substituting one, so no caller is handed a
> rendering it cannot play in place of one it can.

**Two members, and the redundancy argument does not reach them.** *What this
implementation can produce* and *what this rendering is in* are two questions,
not one asked twice: the first is a capability read before a call, the second a
fact about a value returned by one. What would have been redundant is a format
property beside a returned `media_type` that could disagree with it, and the
clause above is what forbids the disagreement rather than a second answer.

> **Normative.** Neither Protocol takes a timeout. The deadline is a decorator
> the composition root wires over whichever implementation it built, on
> ADR-0118 §2's ground taken whole — a deadline written into the seam binds one
> implementation, and a deadline written as a wrapper "composes over *every*
> implementation".

> **Normative.** Both Protocols declare **`SpeechError`** as the failure they
> raise — a new `AssistantError` subclass in `core/errors.py` — and it and its
> subclasses are the whole of the vocabulary. A conforming implementation raises
> a `SpeechError`, or a subclass of one, and raises nothing else that is not a
> defect. Neither Protocol raises a `ModelError`, and no lane widens `ModelError`
> to reach a speech engine.

> **Normative.** `SpeechError` carries ADR-0011 §1's and ADR-0013 §1's two class
> attributes, `retryable` and `routable`, with the same meanings and both
> defaulting to `False` — the conservative pair a bare `ModelError` already
> takes. Carrying the axes without reusing the classes is what leaves §11's
> deferred routing wrapper an implementation someone writes rather than a
> contract someone reopens.

> **Normative.** This ADR adds exactly **two** subclasses and no more:
> `SpeechTimeoutError`, `retryable` and `routable` both `True`, raised by the
> deadline decorator; and nothing else, because nothing else has been observed.
> A lane adds a subclass on evidence of a failure mode it has actually seen, the
> way ADR-0011 §1's taxonomy was built, and not on speculation.

> **Normative.** Two argument refusals sit outside that vocabulary and are
> `ValueError`, raised locally before any I/O: a `SpokenAudio` whose `media_type`
> the transcriber's `formats` does not name, and a `format` the synthesizer's
> `formats` does not name. §3 has the engine read both properties before it
> calls, so a conforming engine never provokes either; they exist for the caller
> that is not one.

> **Normative.** The deadline decorator raises `SpeechTimeoutError` and never
> `ModelTimeoutError`.

**Why a speech taxonomy rather than `ModelError`, in ADR-0118's own words.** An
earlier draft of this section reused `ModelError`, and architecture review named
the defect: `ModelError`'s documented subject is that "a language-model provider
failed or returned an unusable response", and `ModelTimeoutError`'s is a provider
that "did not respond within the deadline (HTTP 408 or a timeout)". §5 permits —
and §11 defaults to — a **local** speech engine, of which neither sentence is
true. ADR-0118 refused exactly this reuse for exactly this reason and its
Alternatives say so: "Overloading it would make the one class that currently
means 'the model provider timed out' also mean 'the local embedding runtime
wedged', which are different remedies. The implementing lane may still reach for
a shared base; what §5 forbids is a shared *class* that erases the difference."
`SpeechError` is that shared base, kept separate; the two class attributes are
what carry across without the semantics coming with them.

**And the taxonomy is deliberately two classes.** ADR-0011 §1's six were built
from provider behaviour that had been observed. Nothing has been observed here —
no speech engine is wired, and §13's evaluation has not run — so minting six
speculative siblings would fix a vocabulary against failures nobody has seen. A
bare `SpeechError` "remains valid for a failure that does not fit any subclass,
and is conservatively treated as neither retryable nor routable", which is
`ModelError`'s own docstring applied to a taxonomy at the start of its life
rather than the end.

**What the seams do not decide.** Neither Protocol names a model, a vendor, a
language, a voice, a sample rate or a device. Engine selection, the 3.14-wheel
question and the on-device model's residency are the implementing lane's
evaluation, scoped by §13 and constrained by §5 and §6; they are not decided
here, and no annotation on either Protocol names a type from `models/` or from
any vendor package.

### 2. The composition is one hub-side operation, and the gateway performs none of it

> **Normative.** Transcription, the turn, the disclosure ruling of §7 and
> synthesis are composed in `orchestration`, behind a single call on the
> promoted `AssistantEngine` surface. No adapter in `interfaces/` transcribes,
> synthesises, or sequences those stages, and no adapter calls a
> `SpeechTranscriber` or a `SpeechSynthesizer` at all.

Three separate rules land on the same answer, and it is worth having all three
on the record because each fails differently if the others are read narrowly.

- **Golden rule 3.** A gateway that ran STT, then `converse`, then TTS would be
  running the request pipeline from `interfaces/`. That is business logic in an
  adapter whatever it is called.
- **ADR-0094 §7, through ADR-0168 §1.** The gateway is a spoke, and every
  obligation ADR-0094 places on a spoke binds it. A gateway that transcribed
  would be submitting "a lossy, model-dependent derivation" of source material
  it holds, in place of the material. It is the clause's own worked case: "the
  promoted slice, not a transcript made at the edge".
- **The hub cannot rule on what it cannot see.** ADR-0199's disclosure tier is
  applied to an answer *because the answer is going to be spoken*. A gateway
  that composed the three stages itself would hold the only knowledge that the
  channel is audio, and the hub would compose its reply believing it was writing
  to a screen. The channel has to reach the composer, and §3 is how.

**A second entry, not a change to the first.** `converse` and
`converse_streaming` are untouched — same names, same signatures, same clauses,
same results — exactly as ADR-0173 §4 kept `converse` untouched when it added
the streamed entry. A caller that wants no speech calls one of them and observes
nothing this decision adds.

### 3. The promoted surface gains one member, and the channel is an argument on it

> **Normative.** `AssistantEngine` gains exactly one member, `converse_spoken`.
> It is `async`, it returns a `SpokenTurn`, and it takes four arguments and no
> others: `utterance`, a `SpokenAudio`, positional; and, keyword-only, `plays`,
> a non-empty `tuple[SpokenAudioFormat, ...]`; `timeout`, a `timedelta`; and
> `conversation_id`, an `Identifier | None` defaulting to `None`. One positional
> subject and every other argument keyword-only is ADR-0085 §2's convention,
> unchanged.

The signature that describes, shown rather than marked (ADR-0089 §2):

```text
async def converse_spoken(
    self,
    utterance: SpokenAudio,
    *,
    plays: tuple[SpokenAudioFormat, ...],
    timeout: timedelta,
    conversation_id: Identifier | None = None,
) -> SpokenTurn
```

> **Normative.** `timeout` is the budget for the whole call — transcription, the
> turn and synthesis together — not for the turn alone. `conversation_id`
> carries ADR-0173 §8's meaning unchanged: the conversation to continue, or
> `None` to run in a fresh one, with `UnknownConversationError` where it names
> none this engine can operate on.

> **Normative.** The budget is **threaded** to each stage, which is ADR-0029 §4's
> rule and the one `converse`'s own signature already carries in as many words —
> "the caller's budget, threaded to the seam that owns the deadline". The
> effective bound on a speech stage is the **lesser** of the caller's remaining
> budget and the decorator's configured one (§1), so a stage never outlives the
> call and a generous deployment setting never overrides a tight caller.

> **Normative.** Every expiry has a stated outcome and none is new machinery.
> Expiry inside `transcribe` is a `SpeechTimeoutError`, which §4 translates to
> `TranscriptionFailedError` carrying `SpeechFailure.TIMED_OUT`. Expiry inside
> `synthesize` is a `SpeechTimeoutError`, which §4 degrades. Expiry during the
> turn behaves exactly as it does on `converse`, whose semantics this ADR does
> not change and does not restate. A budget already exhausted when a stage is
> reached is that stage's expiry and is not a separate case.

> **Normative.** Every clause `AssistantEngine`'s docstring binds every method to
> binds this one: the identifier validation before any I/O, the local refusal of
> a malformed argument, ADR-0060's cancellation clause, ADR-0065's
> input-observation clause, and ADR-0085 §8's size limit enforced in both
> directions. The page-size clause has no subject here and the filter-materialisation
> clause has none either; neither is exempted, both are vacuous.

> **Normative.** **This operation is the output channel, and its audience is
> unbounded.** The answer it produces is bound for a loudspeaker: what that
> channel emits reaches whoever is within range of the device with no act of
> theirs, which is ADR-0199 §1's definition of an unbounded audience, and it is
> declared here rather than computed anywhere.

> **Normative.** **No caller supplies the audience and no value on this surface
> expresses it.** There is no audience argument, no audience member on any type
> this ADR adds, and no setting. A caller cannot assert an audience, cannot
> narrow one, and cannot raise this channel's from unbounded to bounded — which
> is ADR-0199 §8's third clause satisfied by having no value there to assert.

> **Normative.** **A bounded spoken channel is a later ADR's**, and it arrives as
> its own declared channel — a further operation, or the spoke surface ADR-0094
> §10 defers — never as an argument added to this one. No lane reads a caller's
> playback capability, its transport, its session, or the device it runs on as a
> declaration of audience (ADR-0199 §1's fourth clause).

> **Normative.** **This section is the surface ADR-0199 §8's second clause gates
> shipping on**, and it discharges it in the narrowest form that clause admits: a
> channel's audience reaches the composing stage from the *operation the engine is
> executing*, and this ADR fixes this operation's. A channel that declares none
> reads as unbounded (ADR-0199 §1), which this one does not need, since it
> declares unbounded outright.

**What is left as an argument, and why it is not an audience in disguise.**
`plays` says what the caller can *render*, not who can *hear*. It is a codec
capability — the same kind of fact as `SpeechTranscriber.formats` on the other
side of the pipeline — and ADR-0199 §1's third clause is explicit that the
posture "is not a function of the modality, the transport, the device, the
authority the request carried, the session that admitted the request, or the
identity of whoever asked". A format is further from audience than any item on
that list. Nothing in §7 reads `plays`, and no implementation may.

**An earlier draft got this wrong in the way ADR-0199 §8 was written to catch.**
It carried a `SpokenChannel` with an `audience` member the caller supplied on
every call, with a one-member vocabulary meaning "the caller can attest nothing".
ADR-0199 §8's third clause forbids exactly that — an ADR deciding this surface
"may not make the audience a value a spoke asserts per request" — on ADR-0094
§5's ground read in the output direction: "a channel that could assert 'I am
private' is a channel that can talk its way into content, and the assertion is
unverifiable at the hub". The one-member vocabulary made the mistake harmless
today and would have made it live on the day a second member landed, which is the
worse half.

**Why `plays` is a tuple and not a set.** `wire/codec.py`'s `project` dispatches
`list | tuple` and has no branch for a `set` or a `frozenset`, so a set-typed
argument would fail closed at the first call — the same fallthrough that decides
§9. Order is not merely tolerated by that constraint but wanted: a preference
order lets a synthesizer produce the caller's first choice it can honour rather
than any choice at all. The Protocol properties of §1 stay `frozenset`s, because
a capability is a set and expresses no preference.

**And the browser tab is not the private audience it looks like.** ADR-0174 §1
records that the recipient program is "a general-purpose runtime this project
did not write, running our front end beside whatever else the owner has open".
When that runtime *speaks*, the answer leaves the screen the session
authenticated and enters a room nobody attested. That is the whole reason this
call cannot borrow `/ask`'s disclosure posture, and it is why the audience the
caller may attest at this rung is nobody.

> **Normative.** The engine chooses the rendering's format itself: the **first**
> member of `plays` that the synthesizer's `formats` property also names. It never asks for one outside that intersection, and it never returns a
> rendering in a format the caller did not name. Where the intersection is empty
> the answer cannot be rendered for this caller, which §4 makes a degradation
> rather than a failure.

> **Normative.** Adding this member bumps `PROTOCOL_VERSION`, on ADR-0124 §9's
> rule as `wire/envelope.py` records it. The obligation falls on the lane that
> adds the member, in the same change.

### 4. What the call returns, and where the line between failing and degrading falls

> **Normative.** `converse_spoken` returns one `SpokenTurn`, a frozen
> `extra="forbid"` pydantic model in `core/types.py` with four members:
> `heard`, the transcript, `NonBlankEncodableText | None`; `outcome`, the
> `TurnOutcome | None` that transcript drove; `spoken`, the `SpokenAudio | None`
> that was synthesised; and `spoken_degraded`, a `bool`.

> **Normative.** `heard` is `None` **exactly when** `outcome` is `None`, and that
> pair is the recording that carried no words: nothing was asked, so nothing was
> answered, no turn ran, no episode was captured and no conversation was
> created. It is not an error and no exception is raised for it.

> **Normative.** Where `outcome` is not `None` it is exactly the `TurnOutcome`
> `converse` would have produced for that transcript, under every clause
> ADR-0170 §4, ADR-0173 §6 and ADR-0197 §8 place on it. This call composes a
> turn; it does not create a second kind of one.

> **Normative.** `spoken` is the rendering of `outcome.reply` and of nothing
> else: it is what `SpeechSynthesizer.synthesize` returned when handed exactly
> that value. There is **one** answer on this call and `outcome.reply` is it —
> §7 composes it for this channel — so nothing here carries a second copy of the
> spoken words. A caller that cannot play audio reads `outcome.reply` and holds
> exactly what was said.

> **Normative.** That the audio is an audible rendering of that text is the
> **synthesizer's** obligation, discharged in its conformance suite, and not an
> invariant of this type. No component decodes, re-transcribes or otherwise
> inspects a rendering to check it, and no lane adds an operation that does.

**Two earlier drafts of this pair were wrong in opposite directions, and the
second correction is what removed the type.** The first said a `SpokenReply`
carried its own `text` and that "the two always agree", which read as a promise
about what the audio *sounds like* and which nothing structural could establish —
a conforming synthesizer can return well-formed audio saying "no" for the text
"yes". The second made `text` the *input* to synthesis, which was enforceable but
became redundant the moment §7 was corrected to ADR-0199 §5: with the answer
composed for this channel there is only one text, `outcome.reply`, and a second
member holding a copy of it is ADR-0084 §3's second length. `SpokenReply`
therefore does not exist; `spoken` is a `SpokenAudio`.

> **Normative.** `spoken` is `None` wherever `outcome.reply` is `None`: a park,
> a recovered resume, and a composition failure each leave nothing to say, and
> nothing is invented to fill the silence. On those shapes `spoken_degraded` is
> `False`.

> **Normative.** `spoken_degraded` is `True` **exactly when** an answer existed
> and speaking it did not complete — synthesis raised, or the rendering would
> have breached §6's bound. It implies `spoken is None` and `outcome is not
> None`. It is never `True` beside a non-`None` `spoken`, because this call
> streams nothing and so has no partial rendering to carry.

> **Normative.** A transcription failure **fails the call**; a synthesis failure
> **degrades it**. The line is whether an answer exists yet: a failure before
> there is one leaves nothing worth returning, and a failure after there is one
> would throw away an answer the user already has — ADR-0170 §8's argument,
> applied on its own terms rather than by analogy.

> **Normative.** The translation at the orchestration boundary is **total and
> stated both ways**, and `SpeechError` (§1) is what makes each set closed. A
> `SpeechError` out of `transcribe` — and nothing else — becomes
> `TranscriptionFailedError`. A `SpeechError` out of `synthesize` — and nothing
> else — degrades under this section. **Every other exception propagates
> unchanged.** So each stage catches `SpeechError` and neither catches
> `Exception`, which is the shape ADR-0170 §8 already fixed for the composing
> stage and the reason it fixed it: a stage that could be wholly broken while
> every call reported the same classified-looking degradation is the state
> hardest to notice.

> **Normative.** A cancellation delivered to `converse_spoken` is **neither** a
> transcription failure nor a synthesis failure. It propagates, after
> cancellation-safe cleanup, under this module's cancellation clause (ADR-0060)
> exactly as it does on `converse` — it never becomes `TranscriptionFailedError`
> and never sets `spoken_degraded`. A cancellation landing inside `transcribe`
> or inside `synthesize` is such a delivery and is governed by this clause and
> not by the two above it.

> **Normative.** An empty format intersection (§3) is a synthesis failure in the
> sense of this section: `spoken` is `None`, `spoken_degraded` is `True`, and no
> synthesizer is called at all. It is discovered before the call rather than
> reported by one, which is why nothing is spent on it.

> **Normative.** A transcription failure raises `TranscriptionFailedError`, a
> new `AssistantError` subclass in `core/errors.py`, declared by this method and
> by no other. It is not a `SpeechError` subclass: it carries no `retryable` and
> no `routable` claim, because whether a second attempt or a second engine would
> help is a property of the seam's failure, not of the promoted surface's. No
> `SpeechError` reaches the promoted surface through this call, which is why the
> wire's error registry gains one code rather than a taxonomy.

> **Normative.** It is raised **`from None`**. The seam's exception is not
> chained across the promoted boundary: neither its message, nor its class name,
> nor its traceback reaches a caller, in process or across the wire.

> **Normative.** What it carries instead is one keyword-only constructor
> argument, `failure`, of type `SpeechFailure` — a closed `StrEnum` in
> `core/types.py` with exactly one member per class of the `SpeechError`
> taxonomy §1 fixes, and therefore exactly two at this rung: `UNCLASSIFIED` for a
> bare `SpeechError`, and `TIMED_OUT` for `SpeechTimeoutError`. A lane that adds
> a `SpeechError` subclass adds its member here in the same change; the two
> vocabularies do not drift apart.

> **Normative.** The member is chosen by walking the caught exception's MRO for
> the nearest class in a mapping of that taxonomy **frozen at import** and
> matched by **object identity**, falling back to `UNCLASSIFIED`. It is never
> derived from the exception's `__name__`, its module, or its message, each of
> which an implementation controls.

> **Normative.** `TranscriptionFailedError`'s signature is therefore
> `(message, *, failure: SpeechFailure)`, and nothing under `wire/` changes to
> carry it: `wire/errors.py`'s `details_of` reads an `AssistantError`'s
> structured detail off its constructor's parameters, excluding `self` and
> `message`, and `wire/codec.py`'s `project` renders an `Enum` by its value. The
> far side reconstructs the same class with the same member, which is the
> substitutability ADR-0084 §4 promotes the surface for.

**This is `models/routing.py`'s `_classify`, applied one boundary further out,
and it is why the chaining an earlier draft required was wrong.** That helper
exists because "`type(exc).__name__` is provider-controlled: a route may be any
`ModelProvider`, so the class it raises can be named anything at all", and it
answers by "walking the MRO for the nearest *known* class" so that "the emitted
string is one of the strings this module snapshotted from its own taxonomy at
import". A speech implementation is the same kind of stranger, and its exception
carries something `models/routing.py` never had to worry about: `SpeechError`
takes arbitrary text, so an implementation that interpolates the clip it could
not decode has put the recording inside the exception. `raise … from exc` keeps
that object reachable as `__cause__` and renders it in the traceback, which
would defeat §8 in the one place §8 cannot see. Suppressing the cause is
therefore not a loss of diagnostics but the condition of the guarantee.

> **Normative.** An earlier draft of this paragraph let an implementation "log
> its own detail at its own seam, where the audio is already in scope", and that
> was a hole in §8 rather than a concession: §8 forbids audio in either log tier
> "by any component on this path", and a transcriber is such a component. A
> speech implementation logs the same audio-free classification and its own
> message, and logs neither the recording, a fragment of it, nor a rendering of
> an exception that might carry one. Nothing is exempted by being inside the
> implementation.

> **Normative.** `heard` is disclosed to the caller on every call that produced
> a transcript. A push-to-talk surface that cannot show the user what it heard
> cannot be corrected by them, and a transcript the hub acted on but never showed
> is the one part of this path a user has no other way to inspect.

**Two shapes a reader should be able to name from the four members alone.** A
recording with no words is `heard` `None`; a turn whose answer could not be
spoken is `spoken` `None` with `spoken_degraded` `True` and `outcome.reply`
present. Neither is reachable from `converse`, and both are legible without
inspecting a payload — the property ADR-0173 §2 asks of the streaming union and
ADR-0170 §4's validator already enforces one level in.

### 5. Where inference runs, and what actually binds it

> **Normative.** Neither Protocol says where inference runs, and no clause of
> this ADR requires a separate process. What binds an implementation that blocks
> is ADR-0118's two-layer containment, taken whole: the deadline is a decorator
> the composition root wires (§1 above, ADR-0118 §2), and the blocking work runs
> off the event loop on threads the implementation owns and bounds, never on the
> loop's default executor (ADR-0118 §7, `models/_embed_worker.py`).

> **Normative.** No implementation of either Protocol performs inference on the
> hub's event loop, and none is wired into `ai_assistant.service` as a resident
> job, a scheduler task or a poll loop.

**Why this is stated rather than "never in the hub process".** That sentence is
#1029's and ADR-0143 quotes it in Context as a thing already binding, but no ADR
rules it, and the one clause that comes close (ADR-0143 §8) has `BatchCompleter`
for its subject. Ruled generally it would condemn the tree's own embedder:
`FastEmbedEmbedder` runs ONNX inference inside the hub process today, contained
by `OwnedWorkers`, and ADR-0118 ratified that shape after argument. So the rule
that transfers is the *containment*, which is what the hub actually needs —
"a live hub with a dead capability, not a live hub that recovers" — and the
process boundary stays available to a later decision that has a model whose
resident memory or crash blast radius earns it (§11).

### 6. Three bounds, one of them new, and the arithmetic that connects them

> **Normative.** `Settings` gains one field, `hub_max_spoken_audio_bytes`,
> bounding a spoken recording **and** a spoken rendering — the same figure in
> both directions, for the reason ADR-0085 §8's limit is symmetric: so a client
> is never silently less capable than the engine it stands in for. It is
> measured on the **decoded** audio, not on its encoded form, because decoded
> length is what an inference call costs. Its default is 512 KiB.

> **Normative.** An utterance over the bound is refused with
> `OversizedValueError` naming the limit and the field, locally and before any
> I/O — base64 decoding is not I/O — exactly as `AssistantEngine`'s fourth
> clause requires of a malformed argument. A *rendering* over the bound is not
> refused: it degrades under §4, because the answer already exists and still
> travels as `outcome.reply`.

> **Normative.** The other two bounds are unchanged and neither gains an
> exemption. ADR-0085 §8c's payload limit — `hub_max_frame_bytes` less §8b's
> 512-byte reserve — applies to the whole serialised payload of this call as it
> does to every other, measured on its canonical UTF-8 JSON encoding. ADR-0168
> §8's `gateway_max_request_bytes` bounds the browser request whole, request
> line, headers and body together, incrementally as `http.read_request` already
> does.

**The arithmetic, so a reviewer can check the default rather than accept it.**
§9 carries audio as base64 text, which is four bytes of payload for every three
bytes of audio, plus two bytes of JSON quoting. 512 KiB of audio is therefore
about 683 KiB on the wire — inside `gateway_max_request_bytes`' 1 MiB default
with room for the request line, the headers and the rest of the arguments, and
far inside the payload limit's ~16 MiB. Read the other way: 512 KiB is about
three minutes of speech at a 24 kbit/s Opus bitrate, which is a long press and a
short monologue. The two bounds meet where they should, and the new one binds
first.

**Why a fourth figure is worth having at all.** Without it, the only ceiling on
a transcription is the payload limit: 16 MiB of audio is on the order of ninety
minutes, and one press would buy an inference nobody budgeted. A bound on the
recording is the only place that cost can be refused before it is incurred.

### 7. The withholding happens inside the turn, and the answer is composed for this channel

> **Normative.** ADR-0199 decides what may be said on a channel of unbounded
> audience, and this ADR decides nothing it decides. What this section fixes is
> where its rules are *applied* on this operation: in `orchestration`, **inside
> the turn**, and nowhere else.

> **Normative.** The withholding is **at supply**, which is ADR-0199 §5's first
> clause taken whole: content withheld from this channel does not reach the
> composing stage among the inputs the reply is composed from. No stage of this
> operation composes a reply and then removes, masks, blanks or rewrites part of
> it, and no component filters, redacts or post-processes `outcome.reply` on any
> ground.

> **Normative.** There is **one** answer on this call and `outcome.reply` is it.
> It is composed for this channel — an unbounded audience (§3) — so where a class
> was withheld it *is* the deflection ADR-0199 §5 shapes, and where none was it is
> the ordinary answer. No larger answer is composed first, none is retained, and
> nothing on this surface carries what was withheld.

> **Normative.** The composing stage is told the audience of the channel the
> answer is bound for, and it reaches it from the operation being executed (§3),
> not from an argument, a session, a transport or a device. This is the only
> input this ADR adds to that stage; ADR-0199 §5's second clause binds unchanged,
> so the stage gains no `ContextProvider`, no `MemoryStore`, no second context
> assembly and no second retrieval, and its context and memories still reach it
> from the turn and from nowhere else (ADR-0170 §2).

> **Normative.** The deflection reaches the user **as speech on this channel**,
> which is what ADR-0199 §8's fourth clause obliges an ADR deciding this
> mechanism to state. It is `outcome.reply`, synthesised by §3's chosen format and
> returned as `SpokenTurn.spoken`, and it is heard rather than merely rendered —
> which is what milestone 19's exit test turns on. A turn on this operation is
> always addressed to the assistant, so ADR-0199 §5's silence clause has no
> subject here: this call never answers with silence.

> **Normative.** No adapter applies, re-applies, relaxes or second-guesses
> ADR-0199's ruling, and none composes, substitutes or amends a deflection.

**Why the earlier draft of this section was wrong, and why the correction is
strictly simpler.** It had the ruling applied *after* the turn composed, with
`outcome.reply` kept byte-unchanged and a reduced spoken text derived beside it —
on the reasoning that the caller was already admitted to `converse` and could see
on screen what it declined to say. ADR-0199 §5 forbids exactly that construction,
in terms, and for two reasons this ADR has no answer to: a filter over composed
prose is content inspection, which §2 forbids as a decision procedure and which
"fails silently on the first sentence phrased in a way the filter did not
anticipate"; and "a composed answer with a hole cut in it" is an utterance a
listener "cannot distinguish from a complete one". The correction removes a type
(§4), removes a member, and removes the only place on this surface where the
withheld content would still have existed.

**The screen is not a loophole, and ADR-0199 §5's last clause is why it need not
be one.** That clause forbids a reply composed for a *bounded* channel being
emitted on an unbounded one; the converse is safe, and this call's answer is
composed for the unbounded one. So the front end may show `outcome.reply` beside
playing it without any further rule, and it shows the same words that were
spoken. What the owner does *not* get from this operation is the withheld
content — for that they ask on a channel of bounded audience, which is the
deflection's own instruction and the surface ADR-0199 §5 has the answer name
where one can be named.

### 8. Nothing about this path retains audio

> **Normative.** No audio — neither the utterance nor the rendering — is written
> to any store, index, trace, audit trail, routing trail, outbox or log, in
> either tier, by any component on this path. It exists in memory for the
> duration of the call and nowhere else. No setting enables retention and no
> configuration value can.

> **Normative.** The turn a spoken call runs is captured exactly as ADR-0074 §3
> captures every turn, at the point its `TurnOutcome` is produced, with its
> content the canonical rendering of the exchange the transcript drove. This ADR
> adds no field to `EpisodicMemory`, no field to `Provenance`, and no record of
> the channel a turn arrived on.

**Not recording the channel is a decision, and it is ADR-0074 §11's.** That
section states outright that "**nothing on a turn records where it came from**"
and names the extension route — an additive field on the episode or on its
provenance — as open and unstarted. Milestone 19's exit test does not read such
a field, and adding one here would put a member on a wire-carried `core` type
with no consumer, which ADR-0124 §9's second limb makes a second compatibility
event for nothing. Milestone 21 is where the trigger and the channel *are* the
point, and §11 defers it there.

> **Normative.** The error path retains nothing either, and this is the half a
> happy-path test cannot show. `TranscriptionFailedError` carries an
> operator-facing message and never the recording, a fragment of it, or a length
> that would let one be reconstructed — and it chains nothing that could, because
> §4 raises it `from None` and carries a project-owned classification in place of
> the seam's exception. §13 makes this a deliberate failure-path test rather than
> an inference from the retention test beside it.

This is the rule `core/types.py`'s `encodable_text` already applies to the values
it refuses to echo, for the reason stated there: "The value may be megabytes of
untrusted text, and — the sharper reason — interpolating it raw would build an
error message that is itself unencodable". Audio has the first half of that
problem and a worse version of the second: an exception carrying a base64 clip
is a recording that has escaped the one path §8 bounds, and it escapes into the
place nobody inspects.

### 9. The wire carries audio as it stands, and nothing under `wire/` changes

> **Normative.** `SpokenAudio` is a frozen `extra="forbid"` model in
> `core/types.py` with exactly two members: `content`, typed `Base64Audio`; and
> `media_type`, a `SpokenAudioFormat` member. It carries a `decoded()` method
> returning the `bytes`, so the decoding convention is written once and no
> consumer re-derives it.

> **Normative.** `Base64Audio` is a public `core/types.py` annotation, spelled as
> that file's existing refinements are —
> `type Base64Audio = Annotated[NonBlankEncodableText, AfterValidator(...)]` —
> and its validation is exactly this: the value is standard base64 as RFC 4648 §4
> defines it, **with** padding, over that section's 64-character alphabet plus
> `=`; it decodes without error; and it is **canonical**, meaning re-encoding
> what it decodes to reproduces it byte for byte. The value is **never
> normalised**: what a caller passed is what crosses the wire and what
> `decoded()` reverses, which is `NonBlankEncodableText`'s own posture and
> ADR-0096 §2's reason for it.

**The canonicality clause is not decoration.** Base64 admits distinct spellings
of one byte string — a non-zero final-group remainder, and a URL-safe alphabet
among them — so without it `SpokenAudio` would have two values for one
recording, `wire/codec.py`'s canonical encoding would faithfully preserve the
difference, and ADR-0087 §4's normalises-nothing rule would make them two values
all the way down. Refusing the non-canonical spelling is what makes one recording
one value; it is also, incidentally, what makes a decoder that quietly ignores
stray characters unable to admit a payload a stricter peer refuses.

> **Normative.** No file under `wire/` changes to carry audio. ADR-0087 §2c's
> scalar table gains no row, `wire/codec.py`'s `project` gains no branch, the
> framing, the envelope and the frame kinds are untouched, and `wire/surface.py`
> derives this method's adapters from its annotations as it derives every other
> method's. The wire client gains the member because it implements
> `AssistantEngine`, and that is the whole of its change.

**Why base64 text rather than a `bytes` row.** A `bytes` row is the more
truthful Python type, and ADR-0194 §5 is a live precedent for adding one — but
it is a precedent for the *cost* as much as for the act: it partially superseded
ADR-0087's enumeration, and doing it again would supersede that enumeration a
second time so that one type could hold binary. It would also put the base64
convention in two places that must agree forever — a hand-written branch in
`project`, since ADR-0087 §3 forbids delegating to `model_dump(mode="json")`,
and a decoder on the far side — where a silent disagreement corrupts audio
rather than failing. Base64 text puts the convention in one validator on one
type, keeps `project`'s fail-closed posture on `bytes` intact for every other
value, and costs the 4:3 inflation §6 has already accounted for. The row stays
available: §11 names the condition that would make it worth its supersession.

> **Normative.** `SpokenAudioFormat` is a closed `StrEnum` in `core/types.py`
> whose members are IANA media types a browser can produce with `MediaRecorder`
> without transcoding. It has exactly two members at this rung —
> `"audio/webm;codecs=opus"` and `"audio/mp4"` — chosen because between them
> they cover the browsers the exit test can be run on. A lane may add a member
> only on a measurement it records; removing one is a change to what was decided
> and takes a superseding ADR.

> **Normative.** The type carries no sample rate, no channel count, no bitrate
> and no duration. The first three are stated by the container, and a second
> answer to a question the payload already answers is the redundancy ADR-0084 §3
> refuses. A duration would be different and worse: the hub cannot verify one
> without decoding the audio, so a declared duration is an unverified claim, and
> §6's bound is on bytes precisely because bytes are what the hub can measure.

> **Normative.** An implementation handed a `media_type` its `formats` property
> does not name refuses it rather than guessing, and the engine refuses it
> locally, before any I/O, on the same read of that property.

> **Normative.** **A refused recording never travels inside the refusal**, and
> this binds every entry point that constructs a `SpokenAudio` from a value it
> did not author — the wire server's argument adapter and the gateway's body
> parse among them. `Base64Audio`'s own validator names the class of defect and
> the position, never the value, on `encodable_text`'s stated ground. That is
> necessary and not sufficient: a pydantic `ValidationError` carries the rejected
> **input** whatever the message says, so each such entry point catches the
> construction failure and raises a project-owned refusal `from None`, carrying
> no input value and no chained cause.

**This is §8's rule reaching the one path §8's own test would have missed.** A
recording rejected at validation has never reached a seam, so no
`TranscriptionFailedError` is raised for it and none of §4's clauses apply — and
a near-valid clip with one bad character is exactly the input an attacker or an
unlucky browser produces. Without this clause the recording would leave the
device, fail to parse, and come back out inside a refusal that a caller renders
and a log records. It also costs `wire/` and `interfaces/gateway/` a refusal
path, which is a change to how a refusal is *rendered* and not to what the codec
*carries*; §9's claim above is about carriage and stands.

### 10. The browser surface is one POST, and the front end runs no speech engine

> **Normative.** The gateway gains one route, `POST /ask/spoken`, mapped onto
> `converse_spoken` in `_ASSISTANT_PATHS` beside `/ask` and `/ask/stream`. Its
> body is one JSON object carrying the call's arguments, exactly as every other
> assistant route's is, bounded whole by `gateway_max_request_bytes`. It is a
> third entry rather than a replacement, and the gateway never chooses between
> the three, never falls back from one to another, and never retries silently
> (ADR-0168 §9).

> **Normative.** The recording is uploaded complete, in one request, and the
> rendering comes back on that request's response. No WebSocket, no protocol
> upgrade, no `EventSource` and no chunked upload — ADR-0175 §1 forbids the
> first three and `http.py`'s refusal of `Transfer-Encoding` settles the fourth.
> Push-to-talk needs none of them: the press ends before the request begins.

> **Normative.** The front end records with `MediaRecorder` and plays with the
> browser's ordinary audio playback. It does not call `SpeechRecognition`,
> `webkitSpeechRecognition` or `speechSynthesis`, and no lane may wire one.

> **Normative.** **Nothing in this ADR authorises microphone capture on a
> browser the gateway serves over a non-loopback origin.** ADR-0174 §7 names
> microphone capture among the capabilities a browser gates on a secure context,
> rules that such a capability "is not authorised by this ADR", and makes a lane
> that finds the surface requires one **stop** and owe "a ratified decision on
> the scheme, rather than working around the requirement, degrading it silently,
> or reaching for a certificate on its own authority". This ADR takes that stop
> rather than working around it: the wave of §13 that builds this section does
> not begin for the remote-browser case until such a decision is ratified and
> merged, and no lane may read this ADR as supplying one, as authorising a
> certificate, or as permitting the requirement to be degraded.

> **Normative.** The **loopback** case is unaffected and is buildable now. A
> browser on the gateway's own machine reaches it over a loopback origin, which
> is a potentially trustworthy origin without any scheme decision at all — the
> classification ADR-0174 §7 says "loopback got… for free and nobody had to
> notice". Everything §1 through §9 decides is likewise unaffected: not one of
> those sections is browser-facing.

**What that costs the milestone, stated rather than absorbed.** `track:voice`
milestone 19's exit test is the owner holding push-to-talk in a browser **on
another device**. That half of it is blocked on ADR-0174 §11's deferred scheme
question and on nothing this ADR can decide — the mechanism is ready, the
browser will not hand it a microphone. The loopback half is reachable as soon as
the waves land. Whoever schedules the milestone owns the choice between ruling
the scheme question and ruling the exit test met on loopback; this ADR's job is
to make the discovery here rather than in the surface lane, which is exactly
what ADR-0174 §7's stop condition exists for. #1668 carries the choice, with
ADR-0174 §7's own survey of the three routes and why it took none.

**Three reasons, and the third is the one that would survive the other two being
argued away.** Some implementations of those APIs transmit to the browser
vendor, which is an egress no boundary in ADR-0174 §1 authorises and which the
owner never chose. `SpeechRecognition` would also be the edge deciding what a
submission means, which ADR-0094 §6 forbids and §7 forbids again. And
`speechSynthesis` would speak text the hub's disclosure ruling never saw — the
front end reading `outcome.reply` aloud is exactly the failure milestone 19's
exit test is written to catch, performed by the browser instead of by us.

### 11. Deferred, by name, each with the condition that fires it

Each of these is deliberately not decided, and each names what would make it
worth deciding.

- **Streamed speech, in either direction.** The rendering comes back whole.
  `FrameKind.CHUNK` and `interfaces/gateway/streams.py`'s NDJSON already carry a
  streamed *text* answer (ADR-0173, ADR-0175 §3), so the carriage exists; what
  does not exist is a reason. **Fires** when time-to-first-sound on a real
  answer is measured and found to be the thing standing between the exit test
  and a usable one.
- **Barge-in** — the owner speaking over a rendering that is playing. **Fires**
  with streamed speech, which it presupposes.
- **A spoken confirmation.** A parked turn speaks nothing at this rung (§4) and
  the front end renders the confirmation on the screen the press came from.
  **Fires** at the first channel with no screen — milestone 20's idle device.
- **A routing or retry wrapper over either speech seam.** ADR-0011's and
  ADR-0013's shape is available and neither is obliged here (§1, and the
  correction in Context). **Fires** when a second engine is configured for the
  same seam.
- **Inference in a separate process.** §5 contains it in-process on ADR-0118's
  terms. **Fires** on a model whose resident memory or crash blast radius makes
  a thread in the hub unacceptable — the same question ADR-0104 answered for
  re-embedding by stopping the hub.
- **A `bytes` row in ADR-0087 §2c.** §9 declines it. **Fires** on a *second*
  type that must carry binary across this surface, at which point one
  supersession buys two types rather than one.
- **Recording the channel on an episode.** §8 declines it, ADR-0074 §11 names
  the additive route. **Fires** at milestone 21, where a capture's trigger and
  channel are the fact being recorded.
- **A spoken channel of bounded audience.** §3 declares this operation's
  unbounded and admits no value that could say otherwise. A bounded one — a worn
  earpiece is ADR-0199 §1's own example — arrives as its own declared channel,
  never as an argument here. **Fires** with the first device that satisfies
  ADR-0199 §1's bounded test, or with the spoke surface ADR-0094 §10 defers,
  whichever comes first.
- **A secure context for a non-loopback browser origin.** ADR-0174 §11 already
  defers it and §7 makes finding it a stop; §10 takes that stop rather than
  working around it. **Fires** at the first browser-facing capability the
  milestone actually needs — which microphone capture now is, so it has fired
  and this ADR is where the firing is recorded.
- **Speaker identification.** #691's `undetermined` attribution channel. Dodged
  by construction at this rung: the press on an authenticated web session is the
  principal (#1318, ruling recorded at opening). **Fires** at milestone 21,
  where a buffer records rooms rather than sessions.
- **A speech implementation that transmits audio off the device.** None is
  wired, none is reachable from a default, and this is ADR-0188's shape taken
  for its reason — a capability nobody chose is not made available by being
  cheap to add. **Fires** on a decision that states what such an implementation
  discloses, given that a recording carries the owner's voice and a transcript
  does not.

### 12. What this ADR is, under ADR-0070 §1 and ADR-0082 §1

> **Normative.** This ADR **partially supersedes ADR-0177**, in ADR-0070 §3's
> sense, and supersedes nothing else wholly or partially. The scope is exactly
> two clauses of ADR-0177 §1 and no other clause of that ADR or of any other:
>
> **(a) §1's enumeration.** "A browser request resolves to calls on exactly these
> **thirty** operations of the promoted engine surface and no others" becomes
> **thirty-one**, the addition being `converse_spoken` and nothing else. §1's
> own arithmetic moves with it, and every other clause of §1 binds the
> thirty-first exactly as it binds the thirty — including that it is reached
> "with the arguments the promoted surface declares and with no others", that the
> gateway "derives none of them, defaults none of them, composes no operation out
> of two", and that `learn` and `next_notification` stay where §1 put them.
>
> **(b) §1's deadline carve-out.** "On this surface the class has exactly two
> members" becomes **three**, the addition being the budget given to
> `converse_spoken`. It is the same class as the turn budget §1 already admits
> for `converse`, `converse_streaming` and `resume` — ADR-0029 §4's caller-owned
> deadline — and it is added by this ratified decision rather than by
> resemblance, which is what §1's "no lane widens it by resemblance" forbids and
> what a decision that names the member does not do.

> **Normative.** Everything else about this ADR is additive: two new Protocols,
> one new member on a provided contract, five new `core/types.py` names —
> `SpokenAudio`, `SpokenAudioFormat`, `Base64Audio`, `SpokenTurn` and
> `SpeechFailure` — three new
> `core/errors.py` names (`SpeechError`, `SpeechTimeoutError`,
> `TranscriptionFailedError`), one new `Settings` field. No other ratified clause
> is read differently after it, and no existing member changes — `ModelError` and
> its taxonomy least of all, which §1 leaves byte-unchanged and unwidened.

**ADR-0175 §6 is satisfied rather than superseded, and the difference is in its
own text.** Its third clause says every other operation "is unreached from a
browser, and **no lane may add one without its own ratified decision**". This
ADR is that decision, so §6 needs no record: it wrote its own route out and this
change takes it. ADR-0177 §1 wrote one for `learn` alone and none for the
enumeration, which is why (a) is a supersession where §6 is not.

**The record ADR-0177's own status line owes is named here and filed.** ADR-0070
§3 and `docs/adr/template.md` put a partial supersession on the *superseded*
ADR's status line, leading, with the parenthesis naming exactly what was
replaced. This lane's fence is this file, so the edit is not made here; the
scope text it owes is `Partially superseded by ADR-0200 (§1's thirty-operation
enumeration, which gains `converse_spoken`, and §1's deadline carve-out, which
gains that operation's turn budget)`, appended to that line's existing
supersession pair as `docs/adr/template.md` directs, and it is tracked as its
own change in #1667. A reader of ADR-0177 who has not seen it is a reader this
paragraph exists to catch.

**Why the record is filed rather than made here, and what is contested about
it.** Two rounds of review asked for the edit in this change, so the ground is
worth stating plainly rather than left to be inferred.

The **decisive** reason is scope, not timing: this lane's fence is this one file,
and a fence exists because a lane cannot see what another lane holds. Widening
one is the dispatcher's call and not a lane's, so the record is written out
verbatim above and filed as #1667 rather than applied to a file this lane was not
given. Nothing about the decision is deferred with it — §12's scope is settled
here, in a marked clause, and #1667 quotes it.

The **timing** question is genuinely unsettled by the texts, and this ADR does
not pretend otherwise. ADR-0070 §1's bullet is headed "recording a supersession
**that has landed**" and then explains that the act "presupposes the superseding
ADR *exists*" — a phrase written to forbid a supersession naming no ADR at all,
not obviously to license one naming an unmerged draft. `CONTRIBUTING.md` →
"Trivial ADR edits" repeats "has landed". Against that, ADR-0200 does exist in
this change and the pair would land atomically. Both readings are available on
the text, which is what makes it a question for whoever holds the fence rather
than a defect in this document; §13 makes the record a precondition of the wave
that would otherwise act on the stale enumeration, so nothing is built on the gap
whichever way it is resolved.

Three near misses, named so that a reviewer can check them rather than take
them:

- **ADR-0087 §2c's enumeration is untouched** because §9 declines the `bytes`
  row. Had it added one, this would have been a partial supersession of the same
  enumeration ADR-0194 already partially superseded, and would have said so.
- **ADR-0170 §4's shapes are untouched.** `spoken_degraded` is a member of a new
  type, not of `TurnOutcome`, and `TurnOutcome` gains nothing here. §4's
  degradation clause is *applied* to a new stage on its own stated reasoning,
  which is a use of a ratified argument rather than a change to a ratified rule.
- **ADR-0094 §7 is applied, not narrowed.** §2 reads it as forbidding
  transcription at the gateway, which is the clause's own worked case for an
  audio-shaped spoke. Nothing here permits a spoke to derive anything.
- **ADR-0199 is consumed and discharged, not touched.** §3 is the surface its §8
  second clause gates shipping on, stated in the narrowest form that clause
  admits; §7 applies its §5 rather than restating it, and states how a deflection
  reaches the user on this channel, which its §8 fourth clause obliges. Every one
  of its rules binds this operation exactly as ratified, and this ADR reads none
  of them more widely: it adds the Protocols, types, setting and method signature
  its §8 first clause says such a lane needs "its own change and, where golden
  rule 5 reaches it, its own ADR" for. This is that ADR.

**No *amendment* record is owed anywhere.** ADR-0082 §1 owes one "when the later
ADR amends a named clause — and not otherwise", and this ADR amends none: the
one thing it changes it *supersedes*, which is ADR-0070 §1's other side and is
recorded above. The three near misses are the whole of what a reader might
otherwise have expected a record for.

### 13. The work order: what the implementing lanes owe

The waves below are what §11's deferrals are cut around; **which of them ride in
one lane is ADR-0137's question and not this ADR's**, on ADR-0143 §9's precedent
for leaving a lane-shape call to the dispatcher. What is decided here is what
each wave must contain if it exists.

> **Normative.** Each speech Protocol's triad — the Protocol, its shared
> `…Contract` conformance suite, and its canonical `Fake…` in
> `ai_assistant.testing` with the `Test…Contract` subclass — **never lands
> alone**. It rides in one lane and one PR with its primary production
> implementation in `models/`, in ADR-0137 §2's sense.

> **Normative.** That lane also carries an end-to-end exercise of the seam by a
> caller: audio in, transcript out for the transcriber, and text in, playable
> audio out for the synthesizer, over the real implementation, offline, with no
> credential read and no socket opened — the technique `tests/models/network_guard.py`
> already carries. The conformance suite alone does not discharge it; ADR-0015 §5's
> implementation contact is a deliverable rather than an intention.

> **Normative.** The `AssistantEngine` member of §3, the `core/types.py` names of
> §4 and §9, the `core/errors.py` name of §4, the `orchestration` implementation
> and the `wire` client's member land in **one** lane, because a member added to
> a *provided* contract with two implementations cannot land in one of them and
> leave the gate green. That lane carries the `PROTOCOL_VERSION` bump.

> **Normative.** The gateway route of §10 and the front end's record-and-play
> land in a lane fenced to `interfaces/gateway/`, briefed against the merged text
> of the wave above, under `track:web-client`'s concurrency rule (#1226 §3).

> **Normative.** That third wave carries **three preconditions**, and a lane
> briefed against it before all three hold is briefed wrong: ADR-0199 ratified
> and merged (§7 — satisfied at `62724fe1`); ADR-0177's status line carrying
> §12's supersession record; and,
> **for the remote-browser case only**, a ratified scheme decision under ADR-0174
> §11 (§10). The loopback case waits on the first two alone.

| Clause | Deliverable | Test item |
| --- | --- | --- |
| §1 | `SpeechTranscriber` and `SpeechSynthesizer` in `core/protocols.py`; `ModelProvider` byte-unchanged | `tests/core/test_protocol_triad.py` passes for both; a test asserts `ModelProvider`'s member set is unchanged |
| §1 (no timeout) | Neither Protocol takes a deadline; a `Bounded…` decorator per seam in `models/` | A test drives the decorator's expiry and asserts the seam itself has no timeout parameter |
| §2 | Composition in `orchestration`; no speech call from `interfaces/` | A test asserts no module under `interfaces/` references either Protocol |
| §3 | `converse_spoken` on `AssistantEngine`, with §3's exact signature | The engine surface closure test; an argument-order test pinning one positional and three keyword-only |
| §3 (version) | `PROTOCOL_VERSION` bumped, with its comment recording why | The handshake test asserting mismatch is refused at connect |
| §4 | `SpokenTurn` and a validator stating §4's invariants both ways | Tests constructing each admissible shape and rejecting each inadmissible one |
| §4 (line) | Transcription raises `TranscriptionFailedError`; synthesis degrades | Two tests, one per direction, over a seam made to fail |
| §5 | Blocking work off the loop, bounded and abandonable; no `service` wiring | A test asserts `ai_assistant.service` holds neither Protocol; a test that a wedged seam does not stall the loop |
| §6 | `hub_max_spoken_audio_bytes`, enforced both ways | A test refusing an oversized utterance before any seam call; a test degrading an oversized rendering |
| §7 | The ruling applied between the turn and synthesis; `outcome.reply` unchanged | A test that a reduced rendering leaves `outcome.reply` byte-identical |
| §8 | No audio in any store, trail, trace or log | A test asserting the data directory and both log tiers hold no audio after a spoken turn |
| §9 | `SpokenAudio`, `SpokenAudioFormat`, the base64 refinement, `decoded()` | A round-trip test; a test that `wire/codec.py` is unmodified; a rejection test per malformed encoding |
| §3 (plays) | `plays` required with no default, a non-empty tuple | A test refusing the call with no `plays` and with an empty one; a test that a `frozenset` does not project |
| §3 (format pick) | The engine picks `plays`' first member the synthesizer names | A test over a synthesizer naming the caller's second choice; a test degrading on an empty intersection |
| §1 (failures) | `SpeechError` and `SpeechTimeoutError` in `core/errors.py`, carrying `retryable` and `routable`; `ModelError` byte-unchanged | A test asserting each seam's declared raises and both class attributes; a test that the deadline decorator raises `SpeechTimeoutError`; a test that `ModelError`'s subclass set is unchanged |
| §4 (translation) | `SpeechError` from `transcribe` becomes `TranscriptionFailedError`; `SpeechError` from `synthesize` degrades; everything else propagates | Three tests: a classified failure each side, and a non-`SpeechError` exception asserted to propagate from both |
| §4 (no chaining) | `TranscriptionFailedError(message, *, failure: SpeechFailure)` raised `from None`; `SpeechFailure` matched by identity over a frozen mapping | A test that `__cause__` is `None`; a test that a seam exception whose message embeds a recognisable fragment leaves no trace of it in the raised error or its rendering; a test that a class named after a known one is still `UNCLASSIFIED` |
| §4 (failure vocabularies) | One `SpeechFailure` member per `SpeechError` class | A test enumerating both and asserting the bijection, so a later subclass cannot land without its member |
| §3 (budget) | The caller's budget threaded to each stage; the effective speech bound is the lesser of it and the decorator's | Three expiry tests — in `transcribe`, in the turn, in `synthesize` — asserting `TIMED_OUT`, `converse`'s own behaviour, and degradation respectively |
| §4 (`spoken`) | `spoken` is the rendering of `outcome.reply` and nothing else | A test that the value handed to `synthesize` is byte-identical to `outcome.reply`; no test decodes the audio |
| §3 (audience) | No audience argument, member or setting anywhere on this surface | A test enumerating this call's arguments and every added type's fields, asserting none expresses an audience |
| §7 (at supply) | The withholding happens before the composing stage; no filter over composed prose | A test that a withheld class never reaches the composing stage's inputs; a test that no component rewrites `outcome.reply` |
| §7 (one answer) | `outcome.reply` is the deflection where a class was withheld | A test that the deflected turn's `reply` carries no span of the withheld content and that `spoken` renders that same value |
| §9 (`Base64Audio`) | The named annotation, padded RFC 4648 §4, canonical, never normalised | Rejection tests per defect class — bad alphabet, missing padding, non-canonical final group, URL-safe alphabet — and a byte-identity round trip |
| §9 (refusal) | Every entry point constructing a `SpokenAudio` from untrusted input refuses `from None` with no input value | Two failure-path tests, in process and through the gateway, with a near-valid clip, asserting the clip appears in neither the refusal, its cause, its rendering, nor either log tier |
| §8 (error path) | No audio in a surfaced error, its cause, or either log tier | A deterministic transcription-failure test whose seam exception embeds a recognisable audio fragment, asserting that fragment appears in neither the raised error, nor its `__cause__`'s rendering, nor either log tier, nor any store |
| §4 (cancellation) | A delivered cancellation propagates from either stage | Two tests cancelling inside `transcribe` and inside `synthesize`, asserting neither degrades |
| §10 | `POST /ask/spoken`; front end records and plays and calls no browser speech API | A route test; a test asserting the bundle references no `SpeechRecognition` or `speechSynthesis` |
| §10 (secure context) | Nothing capturing a microphone on a non-loopback origin ships before ADR-0174 §11's decision | The lane's own precondition, checked at briefing rather than by a test |
| §12 | ADR-0177's status line carries the supersession record, in a change of its own | A reader of ADR-0177 reaches ADR-0200 from its header |

> **Normative.** A lane satisfies the rows of this table that fall inside its
> fence and adds none: a deliverable this table does not name is out of that
> lane and is filed as an issue.

## Consequences

**What becomes easier.** The hub gains a modality without gaining a second
pipeline: one call, composed where every other turn is composed, ruled by the
disclosure decision that already knows about channels. The wire and the gateway
carry it unchanged, so milestone 19 costs no protocol design and no transport
work — the two things a voice rung is usually assumed to cost. And the two seams
are siblings, so a later engine, a later language, or a later routing wrapper is
an implementation someone injects rather than a contract someone reopens.

**What becomes harder.** `AssistantEngine` grows a method and
`PROTOCOL_VERSION` moves, so every spoke is redeployed together — the honest
cost ADR-0124 §9 already names, and `tests/core/test_engine_surface_closure.py`
is what holds the surface's own count rather than a figure written down here. Base64 costs a third again in payload,
which §6 accounts for and which would need revisiting if a rung ever wanted a
long recording. And the tree now has three `bytes`-shaped ceilings in three
layers; §6 states the arithmetic connecting them because nothing mechanical
does.

**What is blocked, and by what.** The remote-browser half of milestone 19's exit
test waits on ADR-0174 §11's scheme decision, which nothing here can supply
(§10, #1668). ADR-0177's status line owes the record §12 names (#1667). Neither
blocks the hub-side waves, which is the useful part of discovering them at the
ADR rather than in a surface lane. ADR-0199 was the third of these when this ADR
was drafted and is no longer: it merged at `62724fe1`, and §3 and §7 are written
against its ratified text rather than against an expectation of it.

**What becomes possible that this ADR does not take.** §3 discharges ADR-0199
§8's shipping gate in its narrowest form — the operation is the channel — so the
richer surface ADR-0199 §9 defers, where a channel declares its audience as part
of an enrolment record, is unblocked rather than pre-empted. When ADR-0094 §10's
spoke surface arrives it declares audiences without superseding anything here,
because there is no vocabulary here for it to contradict.

**What would trigger revisiting this.** Any of §11's firing conditions.
Sharpest: a measured time-to-first-sound that makes a whole-answer rendering
unusable would reopen §10's one-POST shape and, with it, the streaming
deferrals.

**What is unblocked, and what is not.** The three waves of §13 may be briefed
once this merges (ADR-0015 §5). Nothing implements against it before then, the
canonical fakes included. Milestones 20–22 are dependency-ordered behind 19 and
gain nothing here but the deferrals that name them.

## Alternatives considered

**Compose STT, the turn, and TTS in the gateway.** Rejected in §2, on three
independent grounds — golden rule 3, ADR-0094 §7 through ADR-0168 §1, and the
hub being unable to rule on a channel it cannot see. It is the cheapest design
to write and the only one that puts the request pipeline in an adapter.

**Widen `converse` with a channel argument and an optional audio utterance.**
Rejected. It would make every existing caller's call site a place where an audio
argument could appear, put two return shapes behind one signature, and break the
structural conformance of every `AssistantEngine` implementation at once —
ADR-0021 §3's asymmetry, and the reason ADR-0173 §4 added a second entry rather
than widening the first.

**Add `bytes` to ADR-0087 §2c and type `SpokenAudio.content` as `bytes`.**
Rejected in §9, with the row left available under a named condition. The
truthful Python type is worth having; a second partial supersession of one
enumeration, and a base64 convention duplicated between a hand-written
projection branch and a far-side decoder, are not worth it for one type.

**Carry the recording as a distinct frame kind, beside `REQUEST` and `CHUNK`.**
Rejected. It would put a second framing beside the one ADR-0084 §3 freezes
permanently, for a payload that fits the existing one; `FrameKind`'s own
docstring records how much argument the *fifth-to-sixth* member cost. §9's
measurement is that no new carriage is needed, and a carriage added without a
need is one every peer must implement forever.

**A WebSocket for the browser leg.** Rejected by ADR-0175 §1 before this ADR
reaches it, and it would buy nothing here: push-to-talk uploads a finished
recording, and the press ends before the request begins.

**Let the browser transcribe and synthesise with its own speech APIs.**
Rejected in §10. It is by far the cheapest path to a demo and it fails the exit
test by construction — the browser would speak an answer the hub's disclosure
ruling never saw.

**Retain the audio, so a transcription can be re-read.** Rejected in §8. ADR-0094
§7's "only artifact that can be re-read" argument is about what a spoke *submits*,
not about what a hub *keeps*, and the milestone's exit test needs no re-reading.
A stored voice corpus is a decision with its own disclosure surface, and it is
not one this ADR should make in passing.

**Reuse `ModelError` and its taxonomy as the speech seams' failure vocabulary.**
Rejected in §1 after architecture review, on ADR-0118's own ground: the classes
mean *a language-model provider* failed, §5 permits a local engine, and
overloading them "would make the one class that currently means 'the model
provider timed out' also mean 'the local … runtime wedged', which are different
remedies". It was tempting for the same reason ADR-0118 found it tempting — the
classes exist and the two axes are exactly what a later routing wrapper wants —
and the axes are kept without the semantics.

**Chain the seam's exception across the promoted boundary with `raise … from`.**
Rejected in §4 after both lenses raised it in one round. It reads as the
diagnostic-preserving choice and is the opposite: `SpeechError` takes arbitrary
text, so an implementation that interpolates the clip it could not decode puts
the recording in `__cause__` and in the traceback, where §8's guarantee cannot
reach it and where nobody looks. The classification carries what a caller can act
on; the implementation's own detail belongs in the implementation's own log.

**Carry the audience as a value the caller declares on each call.** Rejected in
§3, and it is the alternative this ADR spent two drafts on: first deferring the
vocabulary to ADR-0199, then fixing a one-member vocabulary here. ADR-0199 §8's
third clause forbids the shape outright — an ADR deciding this surface "may not
make the audience a value a spoke asserts per request" — and its ground is
ADR-0094 §5 read in the output direction. What replaced it costs nothing: the
operation is the channel, its audience is declared in this text, and there is no
value on the surface for anyone to assert.

**Apply ADR-0199's ruling after the turn composed, keeping the full answer
beside a reduced spoken one.** Rejected in §7. It is the intuitive design — the
caller can see on screen what the hub declined to say — and ADR-0199 §5 forbids
it in terms, because a filter over composed prose is content inspection and a
composed answer with a hole in it is indistinguishable from a complete one. It
also kept the withheld content alive on the surface, which is the property the
correction removes.

**Constrain the synthesizer to one format every caller can play.** Rejected in
§1 and §3. There is no single media type every recording browser produces and
every playing client accepts, and a native spoke at milestone 21 has different
constraints again; a caller-declared preference order costs one member on a type
the call already carries and survives all three.

**Record the channel on the captured episode.** Rejected in §8 for this rung and
deferred to milestone 21 in §11. It is additive whenever it is wanted, and
adding it now would put a member on a wire-carried `core` type with no consumer.
