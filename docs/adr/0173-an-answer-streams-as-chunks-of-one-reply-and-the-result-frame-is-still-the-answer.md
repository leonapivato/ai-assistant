# 173. An answer streams as chunks of one reply, and the result frame is still the answer

- Status: Proposed
- Date: 2026-08-21
- **This ADR is milestone 18's ruling on `track:conversation` (#1312)**, the
  milestone whose exit test is *a streamed answer over the wire, resumed
  mid-conversation, from the CLI*. ADR-0170 gave the pipeline a stage that speaks
  and returned its answer whole; this decides how that answer reaches a device
  while it is still being composed.
- **It decides `core` surface and is therefore reviewed under both lenses**
  (`CONTRIBUTING.md` → "Stop when the required reviews are green": a change is
  contract-surface "when it is the ADR deciding that surface", though this PR is
  prose only). §§2, 4 and 5 are the surface: a promoted chunk type, one method on
  `AssistantEngine`, and one **new sibling Protocol** with the triad
  `CONTRIBUTING.md` → "Adding a Protocol" requires. Every implementation is a
  separate lane against this ADR once it is merged (golden rule 5, ADR-0015 §5).
- **It partially supersedes two ADRs, in four named clauses, and each one's
  `Status` line and dated note ride this change** (ADR-0070 §1, ADR-0083 §15).
  **ADR-0085** is superseded twice, in §11 below: §8a's envelope table enumerates
  the five frame kinds "and no others", and §2 adds a sixth; §8c obliges every
  implementation to enforce the payload limit "on results before return", and §4's
  streaming method has no single result to enforce it on. **ADR-0170** is
  superseded twice, in §§6 and 7. §6 replaces §4's
  clause that `reply_degraded` is "never `True` beside a non-`None` `reply`",
  because streaming creates a shape ADR-0170 could not have: an answer that
  **began and did not finish**. §7 replaces §8's clause naming
  `ModelProvider.complete()` as the one call an answer-owing pass originates,
  because a streaming pass spends that call at a different seam. §8's *budget* —
  one model call per answer-owing turn — is restated intact and is not reopened.
  Every other clause of ADR-0170 stands, and §§3 and 6 of it are load-bearing
  here rather than merely surviving.
- **Nothing here is cited toward the `tools/` egress seam, and no egress boundary
  moves.** ADR-0154 §2's clauses stand whole, ADR-0017 §3's fourteen conditions
  are neither discharged nor relaxed, no tool is registered and no destination is
  approved. ADR-0170 §1 already traced a reply against ADR-0124 §1's three
  boundaries and found it on boundary three; chunking changes how many frames
  carry that answer and changes nothing about what crosses or where.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-21**,
  the durability form ADR-0100 established. Refs #1312.

## Context

### What milestone 18 asks for, and how much of it the tree already has

#1312's milestone 18 reads: "the hub-side half of streaming (chunked reply frames
on the wire), conversation resume carrying context; what `track:web-client`
milestone 14 needs from the hub, built here." Two halves. Only one of them is
open, and saying so first is what keeps this ADR from ruling on ground that is
already ruled.

**Conversation resume carrying context already works, end to end, and reaches the
composing stage.** `Engine._converse` resolves the conversation through
`ConversationLifecycle.begin`, reads its tail through
`ConversationLifecycle.history`, and threads the result into
`LearningLoop.respond` as `history`. `respond` folds it into the turn:

```python
preceding = recent + retrieved
memories = preceding + await self._supplement(goal.statement, preceding=preceding)
```

That is ADR-0074 §5's ruling in the tree — "the conversation's recent turns are
handed to the planner as part of `memories`" — and because ADR-0170 §2 gives the
composing stage the whole `TurnResult`, the tail reaches the composer by the same
route, with no second read and no new parameter. `AssembledHistory` already skips
an id that no longer resolves rather than failing, and already reports
`degraded`, which `respond` folds into `memory_degraded`. The promoted surface
already carries `recent_conversations`, `conversation` and `forget_conversation`,
and `converse` already takes `conversation_id` documented as "the conversation to
continue".

So the milestone's resume half is delivered, by ADR-0074 §5 and ADR-0170 §2
together, and this ADR records that rather than re-deciding it (§8). What is
genuinely undecided is not what a resume carries. It is **what a conversation
holds when a stream is cut mid-answer**, which is a question only streaming can
ask, and §9 is where it is answered.

### The wire is serial, and the affordance for this was reserved a long time ago

ADR-0084 §3 made a connection strictly serial — "a request frame sent while
another is outstanding is a protocol violation, and the connection is closed" —
and made the mismatched-response rule its mirror. It then wrote down, in terms,
what the correlation id was being paid for:

> So the correlation id has one job today and one reason to exist tomorrow.
> Today it detects exactly the desynchronisation above. Tomorrow it is what lets
> multiplexing or a progress stream be added *additively* — ADR-0042 §5's
> deferred extension — without renegotiating a frame that had nowhere to put an
> id.

`wire/envelope.py` carries that sentence beside `Envelope` itself. ADR-0084 §11
listed streaming among the deferrals and named the condition: ADR-0042 §5
"deferred it until a progress-emitting stage exists; none does." ADR-0094 §2
declined to spend the affordance and said the mechanism "is an additive wire
decision owing its own ADR". ADR-0170 §9 named the milestone and pointed at the
same place — "the hub-side half of streaming is milestone 18 of #1312 — where the
correlation id's reserved second job (ADR-0084 §3) is the affordance to spend."

This is that ADR, and the condition has fired: ADR-0170's composing stage is the
progress-emitting stage that did not exist. Four texts pointed here; none of them
decided anything this one now has to unpick.

### The model seam cannot stream, and the two wrappers are why that is not a small gap

`ModelProvider` has exactly one member. `complete` takes a `Sequence[Message]`
and returns "the assistant's reply as a `Message`" — a whole one. There is no
`stream`, no async-iterator return, no delta callback. `ComposingStage.compose`
consumes precisely that and nothing else, and its own docstring records the
budget: it "originates **exactly one** `ModelProvider.complete()` call
(ADR-0170 §8)."

The library underneath does stream — `pydantic-ai` exposes it, and
`PydanticAIProvider` uses only `Agent.run()`. The corpus already knows this and
already wrote down where it would matter: ADR-0011 §7 defers precise timeout
classification "until streaming, where pydantic-ai does let bare `httpx` errors
escape from chunk reads", and `models/provider.py` repeats it beside `_classify`.

So the gap is real and it is not merely "call a different library method". The
production seam is `RoutingProvider(RetryingProvider(PydanticAIProvider))`, wired
that way deliberately by ADR-0013 §3, and **neither wrapper can forward a stream
the way it forwards a completion.** `RetryingProvider` snapshots the conversation
and re-issues the whole call on a retryable failure; `RoutingProvider` catches a
`ModelError` and tries the next route on `exc.routable`. Both are correct because
a completion is atomic: nobody has seen anything until it returns, so a second
attempt is invisible. A stream is not atomic. Once a delta has been handed
upward, a retry produces a *second* answer to a question already half-answered,
and a fallback route produces a different one — and no clause anywhere says which
of the two the user was reading.

That asymmetry is what decides the shape of the model half (§5), and the corpus
has already ruled the same fork once, for the same seam, on grounds that transfer
almost word for word.

### What a cut stream costs, read against the code that would have to survive it

`Engine._capture` runs *after* `_compose` returns, and folds the composed text
into the `TurnOutcome` at one point. `ConversationTurn` indexes one whole episode
per turn; there is no partial-turn, in-progress or token-level state anywhere in
the conversation schema. And ADR-0170 §9 left open, on #1314, "whether the
composed answer joins the episode the turn captures" — it does not today.

Read together, those three facts say exactly what a dropped stream costs, and it
is worth stating before the decision rather than discovering it after: the turn's
*record* survives, because capture writes the episode either way; the turn's
*prose* does not, because the reply is not in the episode and there is nowhere
else it is kept. That is a residual this ADR accepts and names (§9), not one it
can close — closing it is #1314's, and #1314 is `track:memory` ground.

## Decision

### 1. A streamed answer is many frames answering one request, and the request is still one request

> **Normative.** A streaming request is one request frame, carrying one
> correlation id, answered by **zero or more chunk frames followed by exactly one
> terminal frame** — a result frame or an error frame. Every frame of the answer
> carries the request's correlation id, and the terminal frame is the last frame
> of the exchange.

> **Normative.** ADR-0084 §3's serial rule binds unchanged. A connection carries
> one outstanding request at a time; a request frame arriving while a stream is in
> flight is the same violation it is today and takes the same answer, a close
> rather than a correlated error. This ADR adds no multiplexing, and no lane cites
> it toward any.

> **Normative.** The hub **notices that violation while the stream is running**
> and stops writing: it does not finish the stream and close afterwards. A
> streaming exchange therefore needs the concurrent read ADR-0131 §2a already
> obliges for an outstanding poll, and a lane that streams without one has not
> implemented this clause.

**That second clause is stated because the tree has already been caught by its
absence once.** ADR-0131 §2a records that "an earlier draft claimed
`_serve_requests` needed no new branch at all, and that claim was wrong" — a
long-running dispatch leaves nothing reading the socket, so nothing observes what
arrives on it. `_dispatch_poll` grew a watcher for exactly that. A stream is the
second long-running dispatch this transport has, it has the same blind spot, and
the window is now open on every answering turn rather than only on a poll.

> **Normative.** The hub still writes no frame except in answer to an outstanding
> request (ADR-0131 §1). A chunk frame is solicited — it answers the request whose
> id it carries — and no lane cites this ADR toward an unsolicited frame, a push
> path, or a hub-initiated request.

**This is the reserved affordance being spent exactly as it was reserved, and it
is worth checking clause by clause rather than asserting it.** ADR-0084 §3's
mismatched-response rule says a response whose correlation id does not match the
outstanding request is a violation; every chunk here carries the id that *does*
match, so the rule is satisfied rather than bent. Its serial rule is about
*requests*, and there is still one. ADR-0131 §1's prohibition is on the hub
writing "unsolicited", and the qualifier governs its whole list — the clause
forbids a frame kind "by which the hub writes to a device **unsolicited**", not a
frame kind as such. A chunk of the answer to an outstanding `ask` is the most
solicited byte on the wire.

**What genuinely changes is the client's read loop, and that is the honest cost.**
`HubClient._call` writes one frame and reads exactly one, and nothing anywhere in
`wire/` iterates over replies today. A streaming call reads until the terminal
frame. That is a real change to the client half and §11 records it rather than
letting a lane meet it by surprise.

### 2. The chunk frame, its payload, and the ordering claim it does not make

> **Normative.** `FrameKind` gains one member and no other: `CHUNK`, wire value
> `"chunk"`. Like every kind but a request it names no method (`wire/envelope.py`
> already refuses a non-request frame that does), and its payload is a promoted
> `core` model, as ADR-0084 §3 requires of a result payload.

> **Normative.** That model is `ReplyChunk` in `core/types.py`, frozen and
> `extra="forbid"` as every promoted model is, carrying exactly one member: `text`,
> typed `NonBlankEncodableText`. A chunk conveying no text is not written at all.

> **Normative.** A chunk carries **no sequence number, no index, and no
> final-frame flag**. Order is the framing's, and the terminal frame is identified
> by its kind.

**The refusal of a sequence number is ADR-0084 §3's own argument, applied
unchanged.** That section refused a length member inside the envelope because
"the frame's length is the prefix below … so a second length inside the envelope
would be a value that can disagree with the one already read — and a frame whose
two lengths disagree has no defensible interpretation." A stream's order is
already fixed by the byte order of a length-prefixed sequence on one connection.
An index would be a second claim about the same fact, and a chunk whose index
disagrees with its position has no defensible interpretation either. The same
reasoning retires a final-frame flag: `FrameKind` is the discriminator, and a
frame that is a chunk by kind and final by flag is two answers to one question.

**`NonBlankEncodableText` rather than `EncodableText`**, for ADR-0170 §3's reason applied
one level down: a blank chunk is a frame that costs a round of framing and says
nothing, and admitting one would oblige every client to decide whether an empty
chunk means "nothing yet" or "something ended". A provider that yields an empty
delta is coalesced by the stage (§5), which is where that knowledge belongs.

### 3. The result frame is the answer; a chunk is a rendering of it in flight

> **Normative.** The terminal result frame carries a `TurnOutcome` exactly as
> `converse` does today, and `TurnOutcome.reply` remains **the only place an answer
> is carried** (ADR-0170 §3). Where the exchange streamed chunks, `reply` is the
> text those chunks conveyed, joined in the order they were written.

> **Normative.** Where a chunk sequence and the terminal `reply` disagree, the
> terminal `reply` is the answer. No client, adapter, setting or later ADR resolves
> that disagreement in the chunks' favour, and no lane treats an accumulated chunk
> sequence as the record of what the assistant said.

> **Normative.** ADR-0170 §6's floor binds unchanged and rides the terminal frame.
> The deterministic step account — the `Disposition`, the named step's `StepStatus`
> and `failure`, and the exit code derived from them — is still the assertion the
> corpus guarantees about what the assistant did, still rendered in addition to the
> answer and never in place of it, and streaming neither suppresses it nor delivers
> it early.

**This is ADR-0170 §6's structure reused one layer out, and the reuse is the
point rather than a convenience.** §6 works because the thing it makes
authoritative — a disposition deterministic code committed — does not depend on
the part that can be wrong. Here the thing made authoritative is the value the
engine returned, and the part that can be wrong is a sequence of frames a client
may have missed, mis-ordered on a buggy reader, or begun rendering before a
failure. A client that renders chunks as they arrive and reconciles to `reply` at
the terminal frame is correct in every case; in the ordinary case the
reconciliation changes nothing, because `reply` is by construction the join of
what was sent.

**Sending the answer twice is the price and it is a small one.** A long answer
crosses the wire once in chunks and once in the terminal payload.
`check_payload` bounds that payload exactly as it does today, so the answer's
ceiling does not move and §8's "no setting of its own" survives (ADR-0170 §8).
What the redundancy buys is that a client may ignore chunks entirely and still be
correct, which is what makes §4's "composes with rather than replaces" true in
practice and not only on paper.

**That redundancy has one consequence which is neither small nor exotic, and this
is the clause that closes it.** A model may yield any number of individually
valid chunks whose joined text will not fit the terminal payload. Every chunk
would pass its own frame check, the hub would have already published prose, and
`check_payload` would then refuse the very `TurnOutcome` §3 makes authoritative —
leaving a chunk-reading client holding an answer and a chunk-ignoring client
holding an error, for the same turn. Under ADR-0170 §8 that case is a refusal
before a byte moves; streaming is what makes it reachable after bytes have moved.

> **Normative.** The streamed answer is bounded by the **same** result-payload
> ceiling ADR-0170 §8 names and gains no setting of its own. No `ReplyChunk` is
> yielded whose text the engine is not already able to carry in the terminal
> `TurnOutcome`, so the join property above holds on every terminal shape this ADR
> admits, and the bound is the engine's to keep rather than the transport's to
> discover.

> **Normative.** Where the accumulating answer would breach that ceiling, the
> engine **stops streaming before the breach** and terminates under §6's ordinary
> partition, decided by whether anything was published: having yielded at least one
> `ReplyChunk` it terminates with §6's fourth shape, `reply` the text actually
> yielded and `reply_degraded` `True`; having yielded none — because the room left
> could not hold even the first chunk — it terminates with §6's pre-commit shape,
> `reply` `None` and `reply_degraded` `True`. It does not yield a chunk it cannot
> repeat, does not refuse a turn whose prose has already been published, and does
> not produce a terminal `reply` that disagrees with the chunks.

> **Normative.** Where the outcome's **non-reply** content alone breaches the
> ceiling, so that no `reply` at all would fit, that is ADR-0085 §8c's oversized
> result and raises `OversizedValueError` exactly as it does on `converse` today.
> This ADR neither creates that case nor changes it, and no lane cites this ADR
> toward softening it.

**Those three outcomes are one rule read at three inputs, not three rules**, and
the partition is worth spelling out because the middle one is easy to collapse
into either neighbour. What decides between them is only ever §6's question —
was anything published? Nothing was published when the room could not hold a first
chunk, so that case is the ordinary pre-commit degradation and *not* a truncation;
`reply` is `None` there because `NonBlankEncodableText` has no way to say "the
empty answer", which is exactly why ADR-0170 §3 chose that type. And the case
where even an answerless outcome will not fit was never about the reply at all: it
is a turn whose plan and retrieved memories overflow the frame on their own, which
`converse` refuses today and which streaming leaves precisely as it found.

**This is a disclosed truncation, and that is exactly the distinction ADR-0170 §8
draws.** §8 forbids "a silent truncation" and makes an over-ceiling answer "that
refusal" instead. Silence is what the flag removes: a client is told in the same
value that the answer is incomplete, and §10 obliges the adapter to say so. A
refusal is still the right answer where nothing has been published — which is
`converse`'s case, unchanged — and is the wrong one once the user is reading,
because it would discard text they have and leave the turn's committed effects
described by nothing.

**The reserve is computable, which is what makes the clause an obligation rather
than a wish.** A `TurnOutcome`'s non-reply content is fixed before composition
begins — its `turn`, `plan`, `memories` and `step` are all settled by the time the
composing stage is reached (ADR-0170 §2) — and the two members capture supplies,
`conversation_id` and `capture_degraded`, are an `Identifier` and a `bool`, both
bounded. So the room left for the reply is known before the first chunk is
written, and the implementing lane measures it rather than guessing at a fraction
of the frame size.

### 4. Streaming is a second entry on the surface, not a change to the first

> **Normative.** `AssistantEngine` gains **one** method, named
> `converse_streaming`, taking exactly `converse`'s arguments in exactly its
> shape — a positional `utterance`, then keyword-only `timeout` and
> `conversation_id` defaulting to `None` — and subject to every clause `converse`
> declares, including its refusals and each of its declared failures.

> **Normative.** Its return annotation is
> `AsyncIterator[ReplyChunk | TurnOutcome]`. It yields zero or more `ReplyChunk`
> values, then **exactly one** `TurnOutcome`, and then stops. The `TurnOutcome` is
> always the last value yielded and is always present unless the call raises.

> **Normative.** That yielded union maps one-to-one onto §1's frames: a
> `ReplyChunk` is a chunk frame, the `TurnOutcome` is the terminal result frame,
> and a raised `AssistantError` is the terminal error frame. **A reader resolves
> the union by frame kind and never by inspecting a payload**, so the kind stays
> the single discriminator §2 makes it and the union adds no second claim about
> what a frame is.

> **Normative.** `converse` is unchanged: same name, same signature, same clauses,
> same one result frame. A caller that wants no stream calls it and observes
> nothing this ADR adds. No other method of the promoted surface changes.

> **Normative.** `wire/surface.py`'s reflection gains a rule rather than an
> exception: a method whose return annotation is an async iterator is adapted by
> **one adapter per member of the yielded union**, selected by the frame kind
> being decoded, where a non-streaming method keeps its single result adapter
> built from its return annotation. No method is adapted by both rules.

**ADR-0042 §5 asked for exactly this and this is the redemption of it**: "it is
added as an **additive** façade method returning an async iterator of progress
events … and it composes with — rather than replaces — the request/response
entry." Two entries for one turn is the deliberate duplication that section
bought, and it is what keeps every existing client, the gateway included, working
untouched.

**The name and the annotation are fixed here rather than left to a lane, and the
corpus is why.** An earlier draft of this ADR deferred both on ADR-0084 §11's
authority. That reads the precedent backwards: §11 deferred "the exact method set
of the Protocol" **to the surface ADR** — to a ratified decision written with
implementation contact — and ADR-0085 then fixed exact keyword-only signatures for
the whole surface. The method name is not an implementation detail on this
surface, it is a wire-visible fact: `wire/surface.py` derives `METHODS` from the
Protocol's concrete names, `wire/server._dispatch` refuses "a request [that] names
… which this build's engine surface does not declare", and ADR-0084 §3's
exact-match handshake makes a build's method set a promise rather than a
convention. Two conforming implementations that chose `converse_stream` and
`converse_streaming` would exchange a version number that says they agree and then
fail on the first call — which is precisely the failure the version exists to
prevent, produced by the one field the version cannot cover.

**Why a union rather than an iterator of one type.** The alternative shapes each
cost more: an iterator of chunks alone has nowhere to put the outcome §3 makes
authoritative; a handle object exposing an outcome property after exhaustion is
not a promoted `core` model and has no wire form; and a wrapper event type with a
`kind` member would put a discriminator inside the payload beside the one already
in the envelope, which is the second-claim problem §2 refuses. Resolving the union
by frame kind keeps exactly one discriminator on the wire and gives the Protocol a
return annotation a second implementation can write against.

> **Normative.** `resume` gains no streaming twin in this milestone. A resumed
> park composes in the ordinary way (ADR-0170 §4) and returns its answer whole.

That is scope and not a judgement that a resumed answer deserves less. It fires
when a resumed answer is observed to be long enough for the difference to be
felt, and it costs nothing to add later because §1's frame shape is already
general over the surface.

### 5. Streaming reaches the model through a sibling Protocol, and `ModelProvider` is not widened

> **Normative.** Streaming inference is introduced as a **new Protocol** in
> `core/protocols.py`, named `StreamingCompleter`, a sibling of `ModelProvider` as
> `BatchCompleter` is. No member is added to `ModelProvider`, no existing member of
> it changes signature or clause, and `StreamingCompleter` does not inherit from
> it. An object may implement both; nothing requires that it does.

> **Normative.** It declares **one** member, `stream`, taking the same arguments
> `ModelProvider.complete` takes in the same shape — a positional
> `messages: Sequence[Message]` and a keyword-only `model: str | None = None` — and
> returning `AsyncIterator[EncodableText]`, the assistant's reply as a sequence of
> text deltas in order.

> **Normative.** `EncodableText` rather than a bare `str`, so ADR-0085 §4c's rule
> that every string this system carries has a UTF-8 encoding binds at this seam as
> it binds at `ModelProvider.complete`'s, whose returned `Message.content` already
> carries it. A delta with no encoding is refused **at the seam**, before it can
> reach chunk construction.

> **Normative.** ADR-0066 §1's precondition binds it identically and for the same
> reason: `messages` must be non-empty and must not end on a `Role.ASSISTANT`
> turn, and a history that fails either is refused before any model is contacted.
> A history containing a `Role.TOOL` turn is refused identically. This ADR widens
> the model seam's admissible history by nothing.

> **Normative.** An implementation may retry, re-issue or substitute a route
> **freely until it yields its first delta containing a non-whitespace character,
> and never after it.** A delta that is empty or wholly whitespace publishes
> nothing, so it commits nothing. Past that first non-blank delta it does not
> restart, does not fall back, and does not re-issue; a failure there is raised
> from the iteration rather than repaired beneath it.

> **Normative.** ADR-0011 §1's error taxonomy binds, and a `ModelError` may be
> raised from the call or from the iteration. Its `retryable` and `routable`
> dispositions are actionable **only before the first delta containing a
> non-whitespace character**; after it, no caller or wrapper acts on them.

> **Normative.** A delta conveying no text is admissible and is the caller's to
> coalesce. A stream that yields no non-blank text at all is the blank-completion
> case ADR-0170 §8 classifies, and degrades identically.

> **Normative.** Coalescing **preserves the answer's text**. A delta that is empty
> or wholly whitespace is joined to the text adjacent to it, never discarded, so
> the concatenation of the yielded `ReplyChunk` texts equals the concatenation of
> the deltas — but for whitespace leading or trailing the whole answer, which the
> stage strips as `ComposingStage` strips it today.

**That clause exists because the obvious reading of "coalesce" loses words.** A
provider yielding `"hello"`, `" "`, `"world"` must not emit the middle delta as a
`ReplyChunk` of its own, since `NonBlankEncodableText` refuses it — and an
implementation that therefore *drops* it produces `"helloworld"`. The blank delta
is not noise to be filtered; it is a separator the model emitted, and it belongs
to the chunk on either side of it. §14 pins the case, because every fake that
yields tidy word-sized deltas hides it.

**ADR-0143 §1 already ruled this exact fork, and its three grounds transfer.** It
introduced `BatchCompleter` as "a **new Protocol** … No member is added to
`ModelProvider`", on the module docstring's own guideline ("prefer adding a new
Protocol over widening an existing one"), on ADR-0021 §3's asymmetry ("a separate
Protocol takes nothing away from anyone and is therefore the presumptive shape"),
and on the observation that `Protocol` is structural so "a new *member* on
`ModelProvider` silently unsatisfies every existing structural implementation at
once — `PydanticAIProvider`, `RetryingProvider`, `RoutingProvider`, the canonical
`FakeModelProvider`, and every test double — and, since `ModelProvider` is
`@runtime_checkable`, changes what `isinstance` answers about all of them." Every
word of that is true here.

**And its fourth ground is stronger here than it was there.** ADR-0143 §1
objected that a member would "oblige `RetryingProvider` and `RoutingProvider` to
forward an operation neither one's policy fits". For a batch that was about
duration and about a handle one provider cannot honour for another. For a stream
it is about a boundary in time: a fallback is not merely a poor fit, it is
**incoherent past the first non-blank delta**, because the user has already read text the
substitute route did not write. A member on `ModelProvider` would have obliged
both wrappers to implement an operation whose safe behaviour contradicts the one
thing each of them exists to do.

**The commit-at-first-delta clause is what makes the sibling honest rather than a
copy.** Without it the new Protocol would look like `complete` with a different
return type, and an implementer would reasonably wrap it in the retry and routing
machinery that already exists — reproducing, one layer down, the failure the
sibling was created to avoid. Stating the boundary as a postcondition means a
conformance suite can pin it, which is the difference between a rule and a hope.

> **Normative.** The composing stage receives an implementation of this Protocol
> by explicit injection from the composition root, as ADR-0170 §2 obliges for its
> `ModelProvider` and on ADR-0028 §4's ground. It obtains one by no other route,
> and reaching through another subsystem's internals to find one is what golden
> rule 1 forbids.

> **Normative.** Where the configured route cannot stream, that is a `ModelError`
> from the call — before any delta — and the pass degrades into §6's pre-commit
> shape. It is not a startup refusal, not a capability flag on the surface, and
> not a reason for the streaming method to be absent from the promoted surface.

Making it a runtime failure rather than a wiring question is what keeps the
promoted surface's method set a fixed property of a build, which is what
`wire/surface.py`'s reflective `METHODS` and ADR-0084 §3's exact-version
handshake both assume. A surface whose membership varied with configuration would
make the handshake's version a weaker promise than it currently is.

### 6. Two commit points, and what degradation means after each

This is where ADR-0170 §4 is partially superseded, and the clause replaced is one
sentence of it.

> **Normative.** The stream has two commit points, nested, and **both are above
> the transport**. The **model seam** commits at its first delta containing a
> non-whitespace character (§5): before it a route may still be substituted, after
> it none may. The **surface** commits at
> the first `ReplyChunk` the engine yields from `converse_streaming`: before it the
> pass may still degrade to no answer at all, after it an answer has been published
> and no clause may pretend otherwise.

> **Normative.** Neither commit point is defined in terms of a frame being
> written, and no lane defines one that way. The engine decides both shapes from
> what it yielded, never from what the transport achieved, so an in-process caller
> and a caller across the wire observe the same outcome for the same turn.

> **Normative.** A composition failure **before the first `ReplyChunk` is
> yielded** — and equally a §3 ceiling stop that yielded none — degrades exactly as
> ADR-0170 §8 rules and changes nothing: the outcome carries `reply` `None` and
> `reply_degraded` `True`, the turn is returned rather than raised, and ADR-0170
> §4's shapes are untouched. This is so whether the failure preceded the first
> delta or followed it.

> **Normative.** A composition failure **after the first `ReplyChunk` is yielded**,
> or a §3 ceiling stop with at least one already yielded, produces a fourth shape
> which ADR-0170
> §4 does not admit and this clause adds: the outcome carries `reply` set to the
> text actually yielded and `reply_degraded` `True`. `reply_degraded` therefore
> means *composing this answer did not complete* — whether because it failed or
> because it ran out of room — and it is `True` beside a non-`None` `reply` on
> exactly this shape and no other.

**Putting the commit point at the surface rather than at the frame is the
correction that makes this clause implementable at all, and the reason is
ADR-0084 §5's.** An earlier draft of this ADR committed at "the first chunk frame
written". The engine cannot observe that: it yields a `ReplyChunk` and something
below it writes a frame, so on a peer that has gone away the engine would have to
learn from the transport whether its own outcome carries a partial reply or none
— transport state reaching across the `core` boundary to decide contract
semantics. Worse, it would have no meaning at all for the in-process caller, who
receives `ReplyChunk` values and never has a frame. ADR-0084 §5 promoted this
façade to a Protocol precisely so that the two are substitutable, and ADR-0131 §2
already refused a clause for the same defect — a typed error "could only ever be
raised by the *transport* … an in-process engine has no connections and could
never raise it, so the same declared contract would mean two different things
depending on which side of the wire the caller stood." A commit point the engine
owns has one meaning on both sides.

**What that costs is a conservative disclosure and nothing else.** A chunk yielded
whose frame never reached the peer makes the outcome report a truncation the user
did not see — but by §9 that peer is gone and the terminal frame is discarded
undelivered too, so there is no client to mislead. The error runs in the safe
direction: the engine may say an answer was cut short when it was merely
undelivered, and never the reverse.

> **Normative.** ADR-0170 §4's other invariants stand unchanged: `reply_degraded`
> is never `True` on a park, never `True` where `turn` is `None`, and never `True`
> on a pass that composed an answer completely. The two-directional
> `model_validator` §4 obliges is widened to admit this shape and to admit no
> other.

**§4's purpose survives whole, which is the test ADR-0070 §1 sets.** §4's stated
reason for the flag is that "a client can tell 'no answer was owed' from 'an
answer was owed and could not be composed' from the value alone". After this
clause a client reads four states from two values and every one of them is
distinct: `reply` absent and the flag clear means no answer was owed; `reply`
absent and the flag set means one was owed and none was produced; `reply` present
and the flag set means one was owed and part of it was produced; `reply` present
and the flag clear means the whole of it was. The clause is widened; the property
it was written to buy is strictly better served.

**Discarding what the user read was the alternative and it is the dishonest
one.** Keeping §4's sentence intact would mean a terminal frame carrying `reply`
`None` after twenty chunks of prose had already been rendered — the wire's
authoritative value contradicting the screen, and every client left to invent its
own reconciliation. That is the state ADR-0084 §3 refuses everywhere it appears:
two answers to one input. Carrying the truncated text instead costs one widened
clause and leaves the client with one rule.

**Why the truncation is not itself a lie, which is the objection worth
answering.** ADR-0170 §6 refuses to let a reply's claim override the step
account, and a half-answer is exactly the kind of text that can end mid-claim.
The flag is the answer: a client that renders `reply_degraded` renders "this
answer is incomplete" beside prose that stops in the middle, and §3 keeps the
deterministic step account on the same screen whatever the prose managed to say.
Nothing about the guarantee changes; one more thing about the turn is disclosed.

> **Normative.** A stream terminated by an **error** frame produced no
> `TurnOutcome`, so there is no `reply` to be authoritative and this ADR guarantees
> nothing about text the client had already rendered. The client reports the
> failure. This is the residual ADR-0170 §8 already accepts for a propagating
> defect, reached one frame later.

### 7. One model call per answer-owing turn, spent at whichever seam the pass uses

This is where ADR-0170 §8 is partially superseded, and again the clause replaced
is one sentence.

> **Normative.** On a pass where an answer is owed, the composing stage originates
> **exactly one** model call. A non-streaming pass spends it on
> `ModelProvider.complete()`, as ADR-0170 §8 rules. A streaming pass spends it on
> §5's sibling seam and originates **no** `complete()` call at all.

> **Normative.** ADR-0170 §8's budget is otherwise restated intact and is not
> reopened. The stage does not loop, does not call again on a failure that call
> reported, does not re-plan, and does not fall back to `complete()` when a stream
> fails — a second attempt is the caller asking again, which is a new turn under
> the caller's own budget. On ADR-0170 §4's park and its recovered resume it
> originates none, and `reply_degraded` stays `False` there.

> **Normative.** What the injected implementation does *below* that seam is not
> this ADR's to constrain, subject only to §5's commit-at-first-delta clause. The
> clause binds the composer and the seam's postcondition, not a provider stack.

**The "no fallback to `complete()`" clause is the one a lane would otherwise
invent, and it has to be refused explicitly.** It looks like free resilience:
the stream failed, so compose the answer the old way and return it whole. Before
the first chunk that would merely be a second call the budget forbids. After the
first chunk it is worse — it produces a complete answer that does not begin with
the text the user already read, and §3 would then make that second answer
authoritative over prose still on screen. The turn gets one call; the caller may
ask again.

**Why the supersession is narrow rather than a rewrite.** ADR-0170 §8's sentence
names a method because at the time exactly one existed. Its argument — a stage
that loops is a stage that spends a caller's budget without being asked, and
retry and fallback are cross-cutting behaviour composed by wrapping (ADR-0011 §2)
rather than by the caller — is untouched and is what §7's second clause restates.
A reader holding only ADR-0170 §8 would nonetheless assert of a streaming turn
that `complete()` was called once, and it is called zero times, so the record is
owed under ADR-0070 §1's test and this change writes it.

### 8. Conversation resume is already carried, and a stream carries it identically

> **Normative.** The streaming method resolves and continues a conversation
> exactly as `converse` does — the same `conversation_id` argument, the same
> `ConversationLifecycle.begin` and `history`, the same `UnknownConversationError`
> — and the composing stage reaches the conversation's recent turns by ADR-0074
> §5's existing route, as part of `TurnResult.memories`. This ADR adds no history
> parameter, no second read, and no conversation surface.

> **Normative.** No `core` type, Protocol member or setting is added for
> conversation resume, and no lane cites this ADR toward one. ADR-0074 §5's
> bounded replay window is unchanged, and `AssembledHistory`'s rule that an
> unresolvable turn is a gap rather than an error binds unchanged.

**Recording that something already works is a decision, not filler, and #1312 is
why.** The milestone names conversation resume beside streaming, so an
implementing lane reading the milestone alone would reasonably go looking for the
resume mechanism to build. It is built. The lane's obligation is to leave it
alone and to prove the streaming path inherits it, which §14 makes a test rather
than an assurance.

**What this means for the milestone's exit test**, which is otherwise easy to
misread: *a streamed answer over the wire, resumed mid-conversation, from the
CLI* is satisfied by streaming one turn, then streaming a second turn under the
same `conversation_id` and observing the second answer draw on the first. It is
**not** a claim that an interrupted stream can be picked up where it stopped, and
§13 declines that by name.

### 9. A cut stream does not abandon the turn, and the prose is what is lost

> **Normative.** A write failure on the connection carrying a stream **does not
> abandon the turn**. The turn runs to its ordinary completion, including its
> capture, and the undelivered chunks and terminal frame are discarded. No lane
> cancels a turn in flight because its client went away.

> **Normative.** No partial-turn, in-progress or token-level state is made
> durable, and no lane adds any for this decision. The conversation record stays
> turn-granular.

**This is ADR-0170 §8's argument, and it is the same argument that made
degradation beat raising.** A turn may have approved a non-idempotent tool,
executed it and durably committed its `StepExecution` before a single word was
composed. Abandoning that turn because a socket closed would leave the effect
committed and the exchange uncaptured — no episode, no conversation turn, nothing
indexing what happened — and the user's natural next act is to ask again, which
re-plans and can perform the effect a second time. Letting the turn finish costs
one turn's tokens for prose nobody reads. The corpus has priced that trade twice
now and reached the same answer both times.

**The residual is real, it is named, and this ADR cannot close it.** The composed
answer is lost to the user, because ADR-0170 §9 left "whether the composed answer
joins the episode the turn captures" undecided on **#1314**, and nothing else
keeps a reply. So a user whose stream was cut sees the turn in their conversation
and cannot read what the assistant said. Closing that is #1314's, it is
`track:memory` ground, and deciding it inside a conversation-track ADR would rule
on a track that is not this one — ADR-0170 §9's own reason for not deciding it.
What changes with this ADR is that the residual acquires a way to be *felt*,
which is worth recording on #1314 rather than leaving to be rediscovered.

### 10. Rendering, and the one thing a chunk boundary must not be able to do

> **Normative.** ADR-0170 §8's neutralisation clause binds every chunk. A chunk is
> engine-supplied text and every adapter neutralises it before display exactly as
> it does the composed reply, the confirmation content, the plan's rationale and a
> policy's reason (ADR-0042 §4).

> **Normative.** Neutralisation is applied to text the adapter has **accumulated**,
> never independently to each chunk as it arrives. An adapter that renders
> progressively neutralises on boundaries its own renderer controls; the boundaries
> the hub chose are never a place where neutralisation can be evaded.

**That second clause is the sharp one and it is not hypothetical.** The chunk
boundaries come from the model's own deltas, so the party that most wants to
smuggle markup past a renderer is the party choosing where the splits fall. An
adapter that calls `interfaces.cli._safe` on each chunk and concatenates the
results neutralises `[/dim` and `]` separately, produces nothing either call
would refuse, and emits live markup when the two are joined on screen. Non-
forgeability is ADR-0098 §2's property and this is the streaming instance of it:
the attribution and the escaping must derive from data the renderer holds, never
from where an untrusted producer chose to break the text.

> **Normative.** An adapter renders the terminal frame's step account whether or
> not it rendered chunks, and renders a `reply_degraded` terminal as the account it
> carries plus a statement that the answer is incomplete — never as a silent turn,
> and never as a failure of a step the account records as succeeded (ADR-0170 §6).

### 11. `PROTOCOL_VERSION` moves, and this time `wire/` moves with it

> **Normative.** The lane landing the streaming method bumps `PROTOCOL_VERSION`
> in the **same change** and appends its reason to the running note in
> `wire/envelope.py` beside the existing entries, as every bump since ADR-0131 §4
> has. The number is deliberately not written here: other lanes may move it first,
> and a number in a ratified document cannot be corrected in place.

ADR-0124 §9's rule is reached twice over, and each limb bites independently. "Any
change to the promoted surface's method set" reaches §4's method — ADR-0124 §9
says so in terms, and calls the consequence honest rather than an oversight. And
a chunk frame is a frame an older peer cannot decode at all: `decode_envelope`
refuses a `kind` that names no known `FrameKind`, and an undecodable frame closes
the connection with no response (ADR-0084 §3), which is precisely the "would be
refused by a conforming peer at the old version" limb.

> **Normative.** ADR-0084 §3's permanent freeze is honoured and nothing this ADR
> adds touches it. The 4-byte big-endian length prefix, the UTF-8 JSON codec, and
> the connect frame's version member keep their representation; the connect
> exchange gains no member; a chunk frame is framed and decoded by the existing
> rules and differs only in its kind and payload.

> **Normative.** Unlike ADR-0170 §7, this decision **does** change modules under
> `wire/` beyond the version constant, and a lane is told so rather than left to
> discover it: the frame-kind enum, the server's one-envelope dispatch, the
> client's one-reply read, and the surface reflection that builds a single result
> adapter from a method's return annotation. What it does not change is the
> framing, the codec, the handshake, or any existing method's mapping.

That is stated because ADR-0170 §7 said the opposite for its own change — "beyond
`wire/envelope.py`'s version constant and its note, no module under `wire/`
changes" — and a lane reading the two ADRs in order would otherwise carry that
relief forward into a change where it is false.

**Two clauses of ADR-0085 are partially superseded here, and both are about the
envelope rather than about the surface.**

> **Normative.** ADR-0085 §8a's envelope table admits `chunk` as a sixth value of
> `kind`, alongside the five it lists. Every other row stands: a chunk frame
> carries `id` and `payload` like every frame, carries no `method` like every
> non-request frame, and adds no member to the envelope.

> **Normative.** ADR-0085 §8b's 512-byte envelope reserve is **unchanged and is
> not recomputed.** `chunk` is five bytes against `connect_ack`'s eleven, so it
> does not touch the worst case §8b's arithmetic is built on, and §8b's headroom
> for a later member is untouched.

> **Normative.** ADR-0085 §8c's limit binds every frame this ADR adds, and its
> enforcement clause is restated for a method that returns an iterator: the limit
> is enforced **on each value before the frame carrying it is written** — on every
> `ReplyChunk` and on the terminal `TurnOutcome` alike — in place of "on results
> before return", which a streaming method has no single point to satisfy. The
> limit itself, the reserve it is computed from, and its enforcement on arguments
> and on errors are unchanged.

**Restating §8c rather than exempting streaming from it is the whole point.** The
clause exists so that both halves refuse the same byte string at the same
boundary, and an iterator does not weaken that — it only moves *when* the check
runs, from once before returning to once before each write. §3's ceiling clause is
the same rule read forward: because the terminal `TurnOutcome` is measured before
its frame is written, and because no chunk is written whose text that frame cannot
repeat, a stream cannot publish text the limit would have refused.

> **Normative.** ADR-0131's delivery rules bind unchanged and need no amendment. A
> streaming turn is not a delivery connection; a poll on a connection that carried
> one is already refused, and a streaming request on a delivery connection is
> already refused. The delivery slot, its per-device limit and its capacity are
> untouched.

### 12. What milestone 14 inherits from this, and what stays milestone 14's

#1312 makes `track:web-client` milestone 14 the consumer shaping this contract,
so what the hub-side frames give a gateway to carry is stated here — and only
that.

> **Normative.** Every frame this ADR adds is an answer to a request the client
> made, so ADR-0094 §2's direction rule is satisfied hub-side without extension,
> and the same shape is what a gateway inherits at the browser edge: whatever
> carries a stream to a browser is established **by the browser**, and the gateway
> writes on it only in answer to something the browser asked for.

> **Normative.** This ADR does not decide the browser-facing carrier and does not
> reopen ADR-0168 §12's deferral of it. Chunked transfer on the request the
> browser made, an event stream on a request it made, or a socket it opened are
> all consistent with the clause above; choosing among them is milestone 14's, and
> no lane cites this ADR toward any of them.

**ADR-0168 §12's reason is worth reading precisely, because it is easy to think
this ADR discharges it and it does not.** §12 declined a push carrier for
milestone 13 because "milestone 13's behaviour needs no server-initiated browser
message at all, and adding a carrier for one before something emits it is the
unspiked seam ADR-0042 §5 and ADR-0084 §11 have twice declined." Something now
emits — but what it emits is **solicited**, so the condition §12 was guarding
against still has not arrived. A gateway can carry every frame this ADR defines
without any server-initiated browser message existing. Whether milestone 14 wants
a socket for other reasons is its own question and this ADR leaves it exactly
where §12 put it.

> **Normative.** ADR-0131 §2's one-delivery-connection-per-device rule is
> untouched, and this ADR does not decide how a gateway fans one delivery out to
> several browsers — ADR-0168 §12 leaves that to milestone 14 and nothing here
> forecloses it.

**One consequence for a gateway is arithmetic and is worth naming.** ADR-0084 §3
makes a connection serial, so concurrent turns need concurrent connections, and a
gateway already counts them against `gateway_max_hub_connections`. A streaming
turn holds its hub connection for the same span the equivalent `converse` holds
one — the turn's own duration — so the ceiling arithmetic does not change. What
does change is that the gateway can now show a browser progress during that span
instead of a spinner, which is the whole reason milestone 14 asked for this.

### 13. What this ADR does not decide

> **Normative.** Beyond §§1–12 and §14, this ADR decides nothing. It adds no
> setting, registers no tool, designates no seam, moves no egress boundary, and
> adds no `core` name other than §2's chunk type, §4's method and §5's Protocol. A
> lane needing any of those needs its own change and, where golden rule 5 reaches
> it, its own ADR.

- **Resuming an interrupted stream.** Declined. It needs durable partial-turn
  state the conversation schema is turn-granular and has none of, and it wants
  the composed answer to be in the episode first (#1314). It fires when #1314
  lands and a measured drop rate makes the case; §9 is the honest behaviour until
  then.
- **Whether the composed answer joins the captured episode** (#1314), which §9
  shows this decision makes more visible and which stays `track:memory`'s.
- **A streaming twin for `resume`** (§4), and its condition.
- **The browser-facing carrier** (§12), which stays ADR-0168 §12's deferral and
  milestone 14's decision.
- **Fanning one delivery connection out to several browsers**, ADR-0168 §12's,
  fired by milestone 14.
- **Progress events that are not reply text.** ADR-0042 §5 spoke of "per-step
  progress" as well as token-level streaming, and this ADR streams only the
  composed answer. A stage emitting structured progress would want its own
  payload type and its own argument about what a client does with it; nothing
  here forecloses it and nothing here provides it.
- **Multiplexing.** The other half of the correlation id's reserved second job
  (ADR-0084 §3) stays reserved and unspent. §1 keeps the connection serial.
- **Precise transport-timeout classification** (ADR-0011 §7), which named
  streaming as its trigger. The trigger fires with the implementing lane, not
  with this ADR; it is a `models/` change with no contract surface and wants
  implementation contact.
- **Whether a blank completion should be refused inside the model seam** (#1324).
  §5 gives the streaming seam the same above-the-seam refusal ADR-0170 §8 chose
  and changes no `ModelProvider` postcondition.
- **The prompt's own text**, which stays `orchestration`'s (ADR-0170 §9).

### 14. What the implementing lanes owe

Plural deliberately: this is more than one lane's work and saying so is part of
the decision. §5's Protocol is a **triad** — Protocol, shared conformance suite,
canonical fake in `ai_assistant.testing`, plus the concrete subclass that runs the
fake through the suite — and `CONTRIBUTING.md` → "Adding a Protocol" makes that
one unit landing together. §§1–4 and §11 are a `wire`-and-`orchestration` change
against that contract. §10 is an `interfaces/` change. A lane sequencing them
takes the triad first, because the rest is written against it.

> **Normative.** The triad lane lands §5's Protocol with a conformance suite
> pinning: ADR-0066 §1's precondition in both refused shapes and the `Role.TOOL`
> refusal; that a stream whose deltas are all blank is the blank case; and — the
> clause a cooperating fake cannot reach — that **no substitution occurs after the
> first non-blank delta**, asserted against a double that would substitute if
> permitted, so the commit boundary is pinned as a boundary rather than assumed.

> **Normative.** The same suite pins the boundary's other side, which a test of
> the commit clause alone will miss: a stream that yields an **empty** delta, and
> again one that yields a **wholly whitespace** delta, and then raises a `routable`
> `ModelError`, may still switch route or retry — because neither could have become
> a `ReplyChunk`, so neither published anything. A suite asserting only that
> substitution stops is satisfied by an implementation that commits on any delta at
> all, which is exactly the resilience this clause refuses to give away for
> nothing.

> **Normative.** The same suite pins §5's encodability refusal: a delta with no
> UTF-8 encoding is refused at the seam rather than surfacing later as a validation
> error from `ReplyChunk` construction.

> **Normative.** The wire lane pins §5's coalescing clause on an **interleaved**
> stream, not only on a blank one: a provider yielding `"hello"`, `" "`, `"world"`
> produces chunks whose join and a terminal `reply` that are both `"hello world"`.
> An implementation that drops the blank delta yields `"helloworld"` and fails
> this test, which is the whole reason it is named rather than left to a fake that
> emits tidy word-sized deltas.

> **Normative.** The wire lane lands §1's frame sequence with tests pinning: that
> every frame of one answer carries the request's correlation id; that a chunk
> frame names no method; that the terminal frame is the last; that a client
> reading the sequence obtains the same `TurnOutcome` a `converse` of the same turn
> would have returned; and that `converse` itself is byte-identical on the wire to
> what it is today.

> **Normative.** The same lane pins §6's four shapes explicitly — no answer owed,
> owed and none produced, owed and partly produced, owed and produced whole — each
> from the two field values alone, **including** a failure injected after the first
> `ReplyChunk` has been yielded, which is the only way the fourth shape is
> reachable.

> **Normative.** The same lane pins §6's second clause — that the commit point is
> the surface's and not the transport's — by asserting the **same** outcome for the
> same turn driven in process and driven across the wire, including a turn whose
> chunk frames fail to reach the peer.

> **Normative.** The same lane pins §1's overlap clause deterministically: a peer
> that sends a second request after receiving a first chunk has its connection
> closed, with **no further chunk frames written** after the violating request was
> readable and no correlated error sent. A test that asserts only the eventual
> close does not satisfy this clause, because an implementation that streams to
> completion and closes afterwards passes it.

> **Normative.** The same lane pins §3's ceiling at its boundary and one step past
> it: a stream whose joined text exactly fills the room the terminal frame has
> terminates whole, with `reply_degraded` `False`; a stream whose next chunk would
> breach it stops before yielding that chunk and terminates with §6's fourth shape.
> Both assert that **no chunk was yielded whose text the terminal `reply` does not
> repeat**, which is the property a chunk-reading and a chunk-ignoring client must
> agree on.

> **Normative.** The same lane pins §3's other two ceiling inputs, which the
> boundary test above does not reach: a turn whose remaining room cannot hold even
> the first chunk terminates with `reply` `None` and `reply_degraded` `True`,
> having yielded nothing; and a turn whose non-reply content alone breaches the
> ceiling raises `OversizedValueError`, as it does on `converse`.

> **Normative.** The same lane pins §9: a connection dropped mid-stream leaves the
> turn completed and captured, with its conversation turn and episode present, and
> nothing re-executed.

> **Normative.** The adapter lane pins §10's boundary clause with a chunk sequence
> that splits an adapter's own markup syntax across a boundary — the split chosen
> so that neither chunk alone would be neutralised — asserting that the rendered
> output carries no live markup. A test that neutralises each chunk and checks each
> in isolation does not satisfy this clause.

> **Normative.** The lane landing §4's method bumps `PROTOCOL_VERSION` and appends
> its note in the same change (§11), and amends the pipeline stage list in
> `ai_assistant.orchestration`'s module docstring only if that list becomes wrong —
> the composing stage is already named there by ADR-0170 §1 and streaming adds no
> stage.

The boundary tests are the ones that matter most and are the easiest to omit,
because every natural test of a stream uses a cooperative fake that yields tidy
deltas and a client that reads every frame. A cooperative fake cannot distinguish
a design whose guarantees are structural from one whose guarantees are a hope
about well-behaved inputs — which is the distinction §5's commit clause, §6's
fourth shape and §10's boundary clause were each written to make.

### 15. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1's test is whether "a reader holding only the earlier ADR [would] now
act differently, or read one of its clauses more widely than it now holds."
Applied clause by clause:

**A record is owed on ADR-0085, and this change writes it** — its `Status` line
and an appended dated note, in the two scopes §11 names. §8a's table states the
envelope's members "and no others" and enumerates `kind` as "one of `connect`,
`connect_ack`, `request`, `result`, `error`"; a reader implementing §8a alone
refuses a `chunk` frame, and §2 makes one valid. That is not a stale roster but a
live decodability rule — `decode_envelope` refuses an unknown `kind` and
ADR-0084 §3 closes the connection for it — so the reader acts differently, which
is ADR-0070 §1's test. §8c's "on results before return" is acted on just as
directly by an implementer, and §4's method cannot satisfy it as written.

**No record is owed on ADR-0085 §1 or §3 for §4's added method, and the corpus
has settled that four times.** §1 says `AssistantEngine` carries "the fifteen
request methods below and nothing else" and §3 lists those fifteen signatures, so
a sixteenth looks like it contradicts them. Four ADRs have already added twelve —
ADR-0130 §9 five, ADR-0131 §4 `next_notification` as "the twenty-fifth method",
ADR-0139 §2 `standing_grants` as the twenty-sixth, and ADR-0151 §1 five connection
operations — taking the tree to thirty-one, and **not one of them recorded a
supersession against ADR-0085**, whose `Status` line named only ADR-0107 before
this change. The mechanism the corpus uses instead is the one ADR-0124 §9 names:
"any change to the promoted surface's method set" bumps `PROTOCOL_VERSION`, and
"adding a method bumps, and that is the honest consequence rather than an
oversight." The running note in `wire/envelope.py` is where each addition is
recorded, against the ADR that decided it. §11 above does exactly that, and this
ADR opens no fifth way of doing it.

**The consequence is disclosed rather than hidden**, as ADR-0170 §3 disclosed the
same shape: ADR-0085 §1's count and §3's listing already read short against the
tree by sixteen methods, and after this ADR by seventeen. That divergence is not
this ADR's to repair — it predates it by four decisions — and #1226's merge-time
numbering practice, not a supersession chain, is what keeps the surface's true
membership discoverable from `wire/surface.py`'s reflective `METHODS`.

**This is where ADR-0170 §3's argument about ADR-0085 §4 does *not* transfer, and
the difference is worth stating because the two look alike.** ADR-0170 §3 declined
to record a supersession for adding a field to a promoted type, on the ground that
"ADR-0085 §4's decision is *which types promote and in what shape at that
moment*", with `Disposition`'s two later members as the settled precedent. That
reasoning holds for a *roster* of types whose authority over later additions was
never claimed. §8a is not a roster: it is the envelope schema that §8b's reserve is
computed from and that a decoder implements, and a frame it does not admit is one
a conforming peer closes the connection over. §8c is an enforcement obligation on
every implementation. Both are acted on directly, so both are recorded rather than
disclosed.

**A record is owed on ADR-0170, and this change writes it** — its `Status` line
and an appended dated note, in the two scopes §6 and §7 name. §4's sentence
"never `True` beside a non-`None` `reply`" is acted on directly by any client and
by the validator §4 obliges, and after §6 it is false on one shape. §8's sentence
naming `ModelProvider.complete()` as the one call is likewise acted on — a lane
implementing ADR-0170 alone would assert it of every answer-owing pass — and
after §7 a streaming pass makes none. Both fail the test, and neither is repaired
by reading ADR-0170 generously.

**No record is owed on:**

- **ADR-0084 §3.** Its serial rule, its mismatch rule and its permanent framing
  freeze all stay true word for word (§1, §11). Its sentence reserving the
  correlation id for "multiplexing or a progress stream" is a deferral *to* a
  decision like this one; a deferral discharged by the decision it named is a
  stacked addition, not an amendment, and the sentence stays true with half of
  it now spent.
- **ADR-0042 §5.** Same shape, more explicitly: it names the form the extension
  takes and §4 takes it. Its "v1 is strictly request/response" describes v1,
  which is not changed retroactively by a later additive entry.
- **ADR-0084 §11 and ADR-0094 §2.** §11 lists streaming as deferred and names the
  condition; §2's direction rule is satisfied without extension (§12) and its
  observation that "the current protocol cannot carry" a hub-initiated request
  stays true, because nothing here is hub-initiated.
- **ADR-0131 §§1, 2.** §1's prohibition is on *unsolicited* frames and §1 above
  reads it as written rather than more widely; §2's delivery rules are untouched
  (§11).
- **ADR-0143 §1.** This ADR follows its reasoning to a second sibling. Being
  cited as a precedent changes nothing about it.
- **ADR-0074 §5.** §8 relies on it exactly as it stands and adds nothing to it.
- **ADR-0011 §2 and ADR-0013 §3.** Neither is narrowed: the wrappers keep every
  behaviour they have on `complete()`, and §5's boundary binds a different
  Protocol they do not implement.
- **ADR-0124 §9.** Its rule is applied, twice (§11). Applying a rule is not
  amending it.
- **ADR-0168 §12.** Examined at length in §12 and found not to fire. Examining a
  deferral's condition and finding it unmet changes nothing.
- **ADR-0170 §§1, 2, 3, 5, 5a, 6.** Each stays true and several are load-bearing:
  §3's "`reply` is the only place an answer is carried" is what §3 above preserves
  rather than erodes, and §6's authority structure is reused rather than relaxed.
  §7's "no module under `wire/` changes" was scoped to ADR-0170's own change and
  is not a rule about later ones; §11 says so plainly so no reader carries it
  across.

## Consequences

- **The assistant answers as it thinks.** Time-to-first-word stops being
  time-to-whole-answer, which on a turn that plans, retrieves, executes a step
  and then composes is the difference between a spinner and a conversation. That
  is the product, and it is the whole reason the milestone exists.
- **The correlation id's reserved second job is half spent.** Four ADRs paid for
  that field and pointed at this moment; a progress stream now uses it and
  multiplexing still does not. The retrofit ADR-0084 §3 bought is collected
  without a flag day, which is what "additive" was supposed to mean and now
  demonstrably does.
- **`wire/` stops being a one-frame-per-request transport**, and the client grows
  a read loop it has never had. That is the largest single cost here and it lands
  in the half of the wire with the fewest tests exercising sequences.
- **The model layer gains a second seam and a boundary in time.** A stream cannot
  be retried or re-routed once it has begun, so the resilience `RetryingProvider`
  and `RoutingProvider` give every other model call is *narrower* on this path —
  available before the first non-blank delta, gone after it. A streamed turn is genuinely
  less resilient than the same turn unstreamed, and that is a real trade rather
  than an implementation detail: a client that would rather have the fallback
  calls `converse`, which is exactly why §4 keeps it.
- **An answer can now be truncated where before it was refused.** ADR-0170 §8
  made an over-ceiling answer a refusal because nothing had been published;
  streaming publishes as it goes, so §3 stops at the same ceiling and discloses
  it instead. That is a strictly better outcome for a long answer and a new state
  for a client to render, and it is the one place this decision changes what a
  user sees on a turn that did not fail.
- **A fourth outcome shape exists**, and clients read four states off two
  booleans where ADR-0170 gave them three. ADR-0170's Consequences already warned
  that "a fourth [flag] would be the trigger to revisit the shape rather than add
  it" — this ADR adds no flag and widens one, which stays on the right side of
  that line, but it moves the turn path measurably closer to wanting one
  structured degradation report instead of three booleans.
- **Conversation resume turns out to have been finished for a while.** ADR-0074
  §5 built it and ADR-0170 §2 extended it to the composer without either ADR
  framing it as a resume feature. Milestone 18 records it rather than rebuilding
  it, and the exit test exercises it.
- **A dropped stream loses the prose and keeps the record**, and #1314 becomes
  the difference between a conversation you can re-read and one you cannot. The
  residual was already there; streaming is what makes it reachable in ordinary
  use.
- **Rendering acquires an adversarial edge it did not have.** A whole reply was
  neutralised once by a renderer that saw all of it; chunks are neutralised by a
  renderer seeing text the model chose where to cut. §10 is cheap to honour and
  silently easy to get wrong, and it is the clause most likely to be
  reintroduced as a bug by a later adapter.
- **Revisit if** #1314 lands, which makes resuming an interrupted stream cheap
  enough to reconsider (§13); if a stage emits structured progress that is not
  reply text, which is the other half of ADR-0042 §5 and would want its own
  payload type; or if a second streaming consumer appears wanting different
  frames, which is when §2's single-member chunk model earns a second one.

## Alternatives considered

**Chunk a completed answer.** Call `complete()` as today, then write the finished
text out in pieces. *Rejected.* It needs no Protocol change and buys nothing: the
user waits the full composition latency and then watches text scroll, which is
strictly worse than receiving it at once. It would also satisfy the milestone's
exit test dishonestly — "a streamed answer over the wire" would be true of a
carrier nothing streams into — which is precisely the unspiked seam ADR-0042 §5
and ADR-0084 §11 twice declined to build, arriving through the door meant to
prevent it.

**Add a streaming member to `ModelProvider`.** *Rejected* in §5 on ADR-0143 §1's
three grounds and a fourth that is stronger here: `Protocol` is structural and
`ModelProvider` is `@runtime_checkable`, so a member unsatisfies every existing
implementation at once; and it would oblige `RetryingProvider` and
`RoutingProvider` to forward an operation whose safe behaviour past the first non-blank
delta contradicts the one thing each exists to do.

**Let the terminal frame carry `reply` `None` after a failed stream, keeping
ADR-0170 §4 intact.** *Rejected* in §6. It buys one unwidened clause and pays
with an authoritative value that contradicts what is on the user's screen,
leaving every client to invent a reconciliation — two answers to one input, which
ADR-0084 §3 refuses wherever it appears.

**Make the chunks the record and let the terminal frame carry no `reply`.** It
would halve the bytes. *Rejected.* It makes an answer's existence depend on a
client having received every frame, so a dropped chunk becomes a silently short
answer rather than a detectable failure — the silent truncation ADR-0084 §3 and
ADR-0073 §4 both refuse — and it would make ADR-0170 §3's "`reply` is the only
place an answer is carried" false, taking §6's authority structure with it.

**Give a chunk a sequence number and a final flag.** *Rejected* in §2 on ADR-0084
§3's own argument against a second length member: order is already fixed by the
framing and kind already discriminates the terminal frame, so both fields are
second claims about facts already settled, and a frame whose two claims disagree
has no defensible interpretation.

**Hold back the first *n* deltas so routing keeps a window to fail over in.**
*Rejected.* It trades the entire product benefit — time to first word — for a
resilience window whose size no one can justify, and it does not remove the
boundary §5 defines, it only moves it somewhere arbitrary and undocumented. A
caller who wants the fallback has `converse`.

**Replace `converse` with the streaming method rather than adding one.** One
entry, no duplication. *Rejected* by ADR-0042 §5 in terms — the addition
"composes with — rather than replaces — the request/response entry" — and by the
tree: the gateway, every existing client and the in-process engine path all
consume a whole `TurnOutcome`, and a caller that wants the whole answer should
not have to assemble it from frames. It would also delete the only path on which
retry and fallback still fully apply.

**Cancel a turn whose client has gone.** It stops paying for tokens nobody will
read. *Rejected* in §9 on ADR-0170 §8's argument: a turn may already have
committed a non-idempotent effect, and abandoning it mid-flight leaves that
effect committed and the exchange uncaptured, whose natural retry can perform it
twice. One turn's tokens is the cheaper side of that trade by a wide margin.

**Defer the whole milestone until #1314 puts the reply in the episode**, so that
a dropped stream is recoverable before streams exist to drop. *Rejected.* It
inverts the dependency: #1314 is `track:memory`'s and is not scheduled by this
track, and the residual it would close is one this system already has for every
turn — a composed answer is unre-readable today whether or not it streamed. §9's
behaviour is honest without it, and streaming is what will make the case for
#1314 concrete rather than theoretical.
