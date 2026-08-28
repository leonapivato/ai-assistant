# 205. A spoken answer's delivery is a fact the device reports, and an unreported answer is never assumed heard

- Status: Proposed
- Date: 2026-08-28

## Context

### Where this comes from

Milestone 19's push-to-talk pass ruled that a press interrupts a playback that is
sounding (#1696, merged), and the front end now does exactly that: `stopPlaying`
ends the source, `playbackInterrupted` writes the notice into the turn that owed
it, and `interruptPlayback` clears the record before the next upload begins
(`interfaces/gateway/assets/app.js`). The owner's phone pass then found what that
ruling left standing, and filed it as **#1700**.

The hub's record still equates *composed* with *heard*. `Engine._capture` writes
one `EpisodicMemory` per outcome (ADR-0074 §3) whose content is the canonical
rendering of the exchange, and `ConversationLifecycle.history` hands the
conversation's recent episodes to the next turn as part of `memories` (ADR-0074
§5). So a reply the owner cut off after three seconds enters the next turn's
prompt whole, and the assistant proceeds as though it had been said. On a channel
whose audience is unbounded (ADR-0200 §3) that is a communication error the system
introduced itself, and it is the only kind of error that gets worse the better the
rest of the mechanism works: the more the assistant remembers, the more confidently
it builds on something nobody heard.

The owner stated two obligations. They are direction, not a proposal, and this ADR
takes them as given:

1. **The assistant knows it was interrupted, and roughly where.** The page knows
   exactly where playback stopped and reports it on the *next* spoken request —
   "previous answer played 3.2 of 9.8 s, interrupted". The hub records that against
   the previous turn, the composing stage is told, so "continue what you were
   saying" resumes from roughly there, and no later turn assumes the rest was
   heard. **Granularity is time, not words**; the synthesizer gives no word
   timestamps and that is enough.
2. **Nothing composed on this channel is treated as delivered until the device says
   so.** The delivery fact defaults to **unknown**.

### The class of assumption the corpus already refuses, cited correctly

#1700 names the family and two of its three citations need correcting. Both
corrections are made here rather than carried forward silently.

**ADR-0131 §1 is exactly on point and is quoted as such.** "A disposed notification
reaches a device only as the **result payload of a request that device sent**." A
notification is never assumed to have arrived because the hub wrote it; arrival is
an answer to a request the device made. This ADR is that posture applied to a
spoken reply: delivery is an answer to a report the device sent.

**The delivery-state refusal is ADR-0078 §8's *and* ADR-0130 §2's, and #1700's
citation of the first is right.** ADR-0078 §8 states it in prose about
`DeferredProposal` — "Delivery state ('was it sent? seen?') is deliberately **not**
on `DeferredProposal`: it is a transport concern, it differs per spoke" — and
ADR-0130 §2 states it as a marked clause about the notification records: "A
candidate carries no delivery state. Whether contact was attempted, reached a
device, or was seen is not a field of the candidate and not a field of its
disposition, and no clause of this ADR may be read as placing one there." ADR-0130
§2's own prose says it is "ADR-0078 §8's refusal kept rather than reversed", and
`core/types.py`'s notification block cites ADR-0078 §8 by name above
`NotificationReach`. So the dispatching brief's correction — that #1700 cited the
wrong ADR — does not hold, and this ADR cites both: ADR-0078 §8 originates the
refusal, ADR-0130 §2 marks it, ADR-0141 restates it.

**Neither refusal is in this ADR's way, and the reason is the subject and not the
strength.** Both are about a **notification** — a candidate, its disposition, a
held record — and about *contact*: was it sent, did it reach a device, was it
seen. This ADR touches none of those types and adds no field to any of them.
Its subject is a **turn** on one operation, and the fact it records is not whether
contact was attempted but how much of a rendering the device reports having played.
§3 states that separation as a clause so no lane has to reconstruct it, and §8
records that ADR-0130 §2 is left standing word for word.

**ADR-0139 §4 is an analogy and is used as one.** #1700 cites it as "a surface
never infers state from an unresolved act". The principle is there — "No surface
infers the **source's current grant state** from either act's outcome … a surface
that has not read it says the source's state is unread rather than asserting one" —
but it is stated for grant amendment and binds surfaces offering amendment. It is
quoted here for its shape, not as a rule that reaches this operation.

### The constraint that decides the shape, and which the issue does not mention

The report arrives with the press *after* the answer it is about. By then the turn
it describes has been captured: `ConversationStore.append` allocated its ordinal
and derived its episode id, and `MemoryStore.add` wrote the episode. **Neither can
be edited afterwards.** ADR-0068 froze the shared record graph — deep immutability
is a property of the `core/types.py` models — and `MemoryStore` offers `add`,
`write_atomic`, `get`, `get_many`, `search`, `delete`, `clear`, `export`,
`purge_expired` and `decide`, and **no update**.

So "record the delivery on the episode" is not a shape that exists. A field on
`EpisodicMemory` could be written once, at capture, and could never move off the
value capture gave it — which is precisely the value the report exists to replace.
Any design that keeps the fact on the episode has to retire and rewrite a record
that other records cite as evidence (ADR-0072 §3), which is a far larger decision
than this one and a worse one.

What *can* carry a fact that arrives late is the **conversation index**. It is an
intent log of turn rows the store owns and writes; `ConversationTurn` already
carries per-turn state that is not content (`parked`, a `ParkedBinding | None`);
`ConversationStore` already has an operation that stamps a row after the fact
(`mark_active`); and — decisively — `ConversationLifecycle.history` **already reads
those rows** on every turn, walking `turns` and looking each episode up. The fact
is therefore available to the composing supply with no second read, which is what
ADR-0199 §5's second clause and ADR-0170 §2 require of anything that reaches that
stage.

### What already binds, and is not relitigated here

- **ADR-0200 §3** fixes `converse_spoken` at four arguments and no others, declares
  this operation's audience unbounded, and admits no value by which a caller could
  say otherwise. §1 below adds a fifth argument and supersedes that count and
  nothing else about the section; the audience clauses bind unchanged, and the
  report is not an audience.
- **ADR-0200 §8** retains no audio anywhere on this path, in either direction, and
  adds no field to `EpisodicMemory` or `Provenance`. This ADR retains no audio
  either (§2) and adds no field to either type (§3).
- **ADR-0199 §5** withholds at supply and forbids composing an answer and then
  editing it. §5 below adds an input to the composing stage in exactly the form
  ADR-0199 §5's third clause uses for the withholding fact, and adds nothing else.
- **ADR-0203 §1 and §2** subtract the withheld supply before the turn plans, over
  one assembly, one retrieval and one filter. A resumed answer is an ordinary turn
  on this operation, so both bind it (§6).
- **ADR-0074 §3, §5 and §9** decide capture, the replay tail and the store surface.
  §3 below adds one member and one operation to that surface; capture's content
  rendering is untouched.
- **ADR-0130 §2 and ADR-0078 §8** refuse delivery state on the notification
  records. Untouched (§8).

## Decision

### 1. The report is a fifth keyword-only argument, and its subject is fixed by the surface rather than named by the caller

> **Normative.** `converse_spoken` takes a fifth argument and no others: `delivery`,
> keyword-only, a `SpokenDelivery | None` defaulting to `None`. Every other clause
> of ADR-0200 §3 binds unchanged — one positional subject and every other argument
> keyword-only (ADR-0085 §2), the threaded budget, the declared unbounded audience,
> and the refusal of any value by which a caller could assert an audience.

The signature that describes, shown rather than marked (ADR-0089 §2):

```text
async def converse_spoken(
    self,
    utterance: SpokenAudio,
    *,
    plays: tuple[SpokenAudioFormat, ...],
    timeout: timedelta,
    conversation_id: Identifier | None = None,
    delivery: SpokenDelivery | None = None,
) -> SpokenTurn
```

> **Normative.** The report's subject is **the most recent turn of the conversation
> `conversation_id` names**, resolved by the `ConversationStore` at the moment of
> the call. No caller names a turn: no turn id, ordinal or episode id is carried by
> the report, accepted from a caller, or disclosed on this surface so that a caller
> could echo one back. A report about some other turn is therefore unrepresentable
> rather than refused.

> **Normative.** A `delivery` supplied beside a `conversation_id` of `None` is
> refused **locally, before any I/O**, as a malformed argument — a fresh
> conversation has no previous turn for the report to be about. That is the local
> refusal ADR-0200 §3 already binds this method to and ADR-0085 §3's convention for
> a malformed argument, and it raises `ValueError` as those refusals do.

> **Normative.** Where the named conversation exists but has no turn to stamp, the
> report is **discarded**: nothing is recorded, nothing is raised, and the call
> proceeds as though no report had been supplied. A conversation whose only turn was
> deleted or whose index entry was reclaimed is an ordinary state (ADR-0074 §5, §8),
> not a fault, and a benign race must not cost the owner the turn they just spoke.

> **Normative.** The report is recorded **before the turn plans**, so a failure,
> degradation, expiry or cancellation later in the call does not lose it. It is a
> fact about a turn that has already happened and it does not depend on this one.

> **Normative.** A turn's delivery is stamped **once**. A second report reaching a
> turn whose recorded state is no longer `UNKNOWN` performs nothing: the row is left
> exactly as it stands and no error is raised. A retry must not overwrite what the
> first report established, and a later report cannot revise it.

> **Normative.** Adding this argument bumps `PROTOCOL_VERSION`, on ADR-0124 §9's
> rule — "any change to the promoted surface's method set or to a method's arguments
> or results". The obligation falls on the lane that adds the argument, in the same
> change.

**Why an argument on this call rather than a member of its own.** #1700 names both
shapes and the choice turns on when the fact is worth having. The report is about
the previous turn *of this conversation* and it is useful to exactly one consumer —
the stage composing the next answer — so it arrives with the next press, in the
round trip that already exists, and reaches that stage without a second frame, a
second admission, a second refusal path or a second gateway route. A
`report_delivery` member would be a second frame per press for a fact whose only
reader is the very next call, and ADR-0084 §3's serial rule means those two frames
are strictly sequential anyway: the press would pay for two round trips to do what
one carries.

**The honest cost of that choice is the turn nobody follows.** Where the owner
interrupts and never speaks again, an argument on the next call is a report that is
never sent, and the turn's delivery stays `UNKNOWN` forever. A separate member
would have recorded it. Two things make that the cheaper failure. First, `UNKNOWN`
is the *correct* record of that state and §4 makes it the default rather than a
gap: nothing reads it as delivered, so an unreported interruption is not
mis-remembered, it is un-remembered. Second, the only consumer of a more precise
value is a turn that never happens; a page closed after an interruption leaves
nothing that would have read the record it did not send. So the shape loses
precision exactly where precision has no reader.

**The report is not an audience and cannot become one.** It says how much of a
rendering a device played, not who was within range of it. ADR-0199 §1's third
clause — the posture "is not a function of the modality, the transport, the device,
the authority the request carried, the session that admitted the request, or the
identity of whoever asked" — reaches this value as squarely as ADR-0200 §3 says it
reaches `plays`. Nothing in ADR-0199's ruling reads `delivery`, and no
implementation may.

### 2. What the report carries, and what it may not

> **Normative.** `SpokenDelivery` is a frozen `extra="forbid"` pydantic model in
> `core/types.py` with exactly three members: `state`, a `SpokenDeliveryState`;
> `played`, a `timedelta | None`; and `rendered`, a `timedelta | None`.

> **Normative.** `SpokenDeliveryState` is a closed `StrEnum` in `core/types.py` with
> exactly three members: `UNKNOWN`, `COMPLETE` and `INTERRUPTED`. Adding a member is
> a change to what was decided and takes its own ratified decision, as does removing
> one.

> **Normative.** The three states are coherent with the two durations, refused at
> validation where they are not. `UNKNOWN` carries `played` and `rendered` both
> `None`. `COMPLETE` and `INTERRUPTED` each carry both, with `rendered` strictly
> positive and `0 <= played <= rendered`; `INTERRUPTED` additionally requires
> `played < rendered`. This is `DeferredProposal`'s coherence-validator shape, taken
> for ADR-0130 §2's stated reason: a value that has already contradicted itself is
> not a report, it is a defect.

> **Normative.** A `delivery` **argument** whose state is `UNKNOWN` is refused
> locally as malformed, before any I/O. A device that does not know reports nothing,
> and the absence of a report is spelled by omitting the argument. `UNKNOWN` is a
> value the hub writes (§4) and never one a caller supplies.

> **Normative.** The report carries **two durations and a state, and nothing else**.
> No audio, no fragment of one, no transcript, no span of what was heard, no word
> count, no character offset, no sample position, no format and no identifier. It is
> not a rendering and it does not permit one to be reconstructed, so ADR-0200 §8's
> retention clause binds this path exactly as it binds every other and is not
> weakened by it.

> **Normative.** Granularity is **time**. No lane derives a word, a sentence or a
> character position from these durations, and no surface promises one.

> **Normative.** A report is a **device's claim**, not a fact the hub established,
> and it is recorded as such. Nothing verifies it: no component decodes the
> rendering, measures it, re-times it, or compares a reported duration against
> anything, and no lane adds an operation that does. ADR-0200 §9's refusal of a
> declared duration on `SpokenAudio` is not read as forbidding this one.

**That last clause needs its argument stated, because ADR-0200 §9 refused a
duration on exactly this path.** Its reason was that "the hub cannot verify one
without decoding the audio, so a declared duration is an unverified claim, and §6's
bound is on bytes precisely because bytes are what the hub can measure" — and that a
declared duration would be "a second answer to a question the payload already
answers". Neither reason transfers. Nothing in this system knows how much of a
rendering was *played*; the device is the only witness there is, so an unverified
claim is not the worse of two available answers, it is the only one. And it answers
a question the payload does not answer at all: the payload says what was sent, and
this says what was heard.

**What a lying device can and cannot do, stated rather than assumed.** A device that
under-reports — claiming `INTERRUPTED` where the answer played out — makes the
assistant offer to continue something already finished, which is a mild
conversational error the owner corrects in one sentence. A device that over-reports
— claiming `COMPLETE` where it interrupted — produces exactly the behaviour the
system has **today**, before this ADR. So the report cannot make the failure it
addresses worse, and there is one principal on this hub (ADR-0099 §1) with no
adversary distinct from the owner. That is why no verification clause is owed and
why one is refused rather than deferred.

### 3. The fact lives on the conversation index's turn row, and on nothing in the memory store

> **Normative.** `ConversationTurn` gains exactly one member: `delivery`, a
> `SpokenDelivery | None` defaulting to `None`. It is the third fact the index
> carries about a turn beside its identity — after `occurred_at` and `parked` — and
> it is state about the turn, not content of it: `ConversationTurn`'s "This store
> holds no content" posture binds unchanged, because two durations and a state are
> not the exchange.

> **Normative.** This ADR adds **no field to `EpisodicMemory`**, no field to
> `Provenance`, mints no memory record, installs nothing in the `MemoryStore`, and
> changes nothing capture writes there. ADR-0200 §8's clause and ADR-0203 §4's
> clause each stay true word for word, and nothing here is read as authority to add
> such a field for any other purpose.

> **Normative.** `ConversationStore` gains exactly one operation, `record_delivery`,
> which stamps the named conversation's most recent turn with a `SpokenDelivery` and
> returns the turn it stamped, or `None` where the conversation has no turn to stamp.
> The store resolves which turn that is; a caller never supplies an ordinal, exactly
> as it never supplies one to `append`. It raises `UnknownConversationError` where
> the conversation is absent or stamped deleted, and `ConversationStoreError` where
> the store cannot be written — the same two refusals `append` carries.

> **Normative.** `ConversationStore.append` gains exactly one keyword-only argument,
> `delivery`, a `SpokenDelivery | None` defaulting to `None`, written onto the row it
> allocates. Capture uses it (§4); no other caller supplies one.

> **Normative.** An absent `delivery` means **the turn produced no spoken rendering**.
> It is never read as delivered, never read as unknown, and never read as a claim
> about a turn that ran on any other operation.

> **Normative.** `delivery` is **not a record of the channel a turn arrived on**. No
> lane, implementation or later ADR reads it as one, infers an arrival channel from
> it, or cites this ADR as authority for recording a channel. ADR-0200 §11's
> deferral of "recording the channel on an episode" and ADR-0074 §11's "nothing on a
> turn records where it came from" are both untouched, and milestone 21's decision is
> neither taken nor narrowed here.

**That clause is a restraint and not a claim of innocence, and the difference is
worth writing down.** On today's surface `converse_spoken` is the only operation
that produces a spoken rendering, so a row carrying a `delivery` is in fact
coextensive with a turn that ran there, and a reader who wanted to could infer the
operation from the field's presence. What this section forbids is *using* it that
way. The fact recorded is about the **rendering's delivery** — an output fact,
about something the hub produced and a device played — and the deferrals it must
not lift are about **origin**: which device was live, where a turn came from, what
triggered a capture. Milestone 21 records those on the episode and about the
arrival; this records one on the index and about the departure. A lane that reached
for `delivery` to answer "what channel was this?" would be answering a different
question with a value that happens to correlate, which is the reasoning ADR-0130 §2
refuses when it keeps delivery state off a record that could carry it.

**Why not a companion record in the `MemoryStore`.** It is the other shape that
survives ADR-0068's freeze — install a new frozen record naming the episode — and
it costs three things this one does not. It puts a citable record in the store the
observer reads (`MemoryWriter.observe` takes episodes), so "the answer played 3.2 of
9.8 s" becomes material a belief could be proposed from. It needs a retrieval rule,
because nothing today fetches records by the episode they qualify, which is a
second read on every turn and the thing ADR-0199 §5's second clause and ADR-0203 §2
exist to prevent. And it duplicates a relation the index already holds, which is
ADR-0074 §10's declined shape arriving from the other direction. The index row is
already read, already store-owned, already carries per-turn state, and is already
Tier 1 local-only (ADR-0004 §2) — which a durable record of what the owner was in
the room to hear ought to be.

### 4. The default is unknown, and it is written rather than inferred

> **Normative.** Capture on `converse_spoken` writes `delivery` as
> `SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)` onto the turn's index row, in
> the `append` that records the turn. It is written **unconditionally on that
> operation** — including where the answer was parked, where `outcome.reply` is
> `None`, and where `spoken_degraded` is `True`. At capture the hub has produced an
> answer and knows nothing about what reached anyone, and that is what `UNKNOWN`
> says.

> **Normative.** No other operation writes a `delivery`. `converse`, `converse_streaming`
> and `resume` capture exactly as they do today, and their rows carry none.

> **Normative.** No setting, default, configuration value or degradation path moves a
> turn out of `UNKNOWN`. Only a device's report does, through §1's argument, and only
> once (§1).

> **Normative.** A turn whose rendering never existed — synthesis raised, the format
> intersection was empty, a bound was breached (ADR-0200 §4) — stays `UNKNOWN`. The
> hub knows in that case that nothing was heard, and this ADR deliberately does not
> mint a fourth state to say so: `spoken_degraded` already told the caller, and a
> second spelling on the index would be a value that must agree with one held
> elsewhere. §8 records the state as available additively and not decided here.

### 5. How the composing stage is told, and why nothing is retrieved a second time

> **Normative.** Where the conversation's previous turn carries a `delivery`, the
> composing stage of the turn being run is **told it as a supplied fact** — the
> state, and where a report was received, the two durations. That is ADR-0199 §5's
> third clause in the form it already uses for the withholding fact: the stage is
> told a fact and composes over it.

> **Normative.** The fact rides the tail that stage's inputs are already assembled
> from. `ConversationLifecycle.history` walks `ConversationStore.turns` and holds
> those rows already, so the composing supply reads it off what was fetched. The
> stage gains **no `ContextProvider`, no `MemoryStore`, no second context assembly
> and no second retrieval**, and its context and memories still reach it from the
> turn and from nowhere else — ADR-0199 §5's second clause, ADR-0170 §2 and ADR-0203
> §2, each binding unchanged.

> **Normative.** The fact is a **supplied input and not part of the episode's
> `content`**. Capture's canonical rendering is byte-unchanged by this ADR
> (`Engine._capture`), and no delivery sentence enters what a later turn replays.

> **Normative.** No stage, adapter, surface or later ADR asserts that an unreported
> answer was heard. Where the previous turn's state is `UNKNOWN` the stage is told
> that it is unknown, and composes accordingly; it is never told, and never
> defaults to, delivered.

> **Normative.** How the stage renders the fact into a prompt — the wording, and
> whether the durations are rounded — is the implementing lane's, bounded by §2's
> granularity clause. No clause here requires a rounding or forbids one.

**Why the fact is supplied rather than written into the content.** ADR-0197 §10
rules that a routed pass's captured episode carries no part of the routed account,
and states the mechanism plainly: "a conversation's recent turns are retrieved into
the next turn's prompt (ADR-0074 §5, ADR-0158 §5), so a capture that folded a routed
listing into the episode would deliver the routed result to a model one turn later".
A delivery sentence in `content` is the same failure with a different payload. It
would be true of one channel and replayed on every channel, it would still be there
three turns later when it means nothing, and it would make an episode's canonical
rendering depend on how the answer happened to be carried — which is the property
ADR-0074 §3 gives it precisely so that it does not.

**The composing stage is `converse_spoken`'s, and this input does not leak to
others.** A turn on `converse` whose conversation's previous turn carries a
`delivery` is a real case — the owner speaks, is interrupted, and then types. That
turn's stage is told the same fact, for the same reason: the previous answer was not
heard, and a text turn that builds on it is wrong in exactly the way a spoken one
would be. The fact is about the previous turn's delivery, not about this turn's
channel, so it is supplied wherever it is known, and §3's absence clause keeps it
from being invented where it is not.

### 6. "Continue what you were saying" is an ordinary utterance

> **Normative.** No intent, routing rule, operation, argument or surface is added for
> resumption. "Continue what you were saying" is an ordinary utterance the composing
> stage answers over §5's supplied fact. No lane adds a route in
> `orchestration/routing.py`, no lane matches on the words, and ADR-0197's routing
> stage gains nothing (ADR-0197 §1's enumeration is untouched).

> **Normative.** A resumption is **composed afresh**. Nothing replays a stored
> rendering, a stored text or a stored audio fragment, and nothing is retained
> between turns to make one available — ADR-0200 §8 binds this path exactly as it
> binds every other, and this ADR creates no store, buffer or cache of an answer.

> **Normative.** The resumed answer is an ordinary turn on an operation whose
> channel audience is unbounded, so **ADR-0199 §3 and ADR-0203 §1 bind it exactly as
> they bind any other**: the supply is subtracted before it plans, and the answer is
> composed for this channel. A lane never reads "continue" as licence to re-emit an
> answer composed for a different supply, nor as a reason to relax the withholding
> because the words were "already said".

**That last clause is the trap this section exists to close.** An interrupted
answer is one the system composed and holds in nothing; the tempting implementation
is to keep it around so "continue" can pick up mid-sentence. It would be a retained
rendering (ADR-0200 §8), and worse, it would be an answer composed under a supply
the *next* turn may not be entitled to — the withholding is decided per turn
(ADR-0203 §1), and replaying prose composed a turn earlier emits an answer this
turn's ruling never saw. Composing afresh over "the previous answer was heard up to
about 3 s of 10" costs a model call the turn was going to make anyway and keeps
every ratified clause true.

### 7. The browser surface gains one body member and nothing else

> **Normative.** `POST /ask/spoken`'s body carries the **browser-owned** arguments
> of §1's signature and no others — `utterance`, `plays`, `conversation_id` and
> `delivery` — bounded whole by `gateway_max_request_bytes`. The gateway reads those
> four members by name and reads no fifth. Every other clause of ADR-0200 §10 binds
> unchanged: `timeout` is still not on that list, no browser value reaches it, a
> `timeout` a body carries is still never read, and the gateway still adds no route,
> no fallback and no silent retry.

> **Normative.** The gateway **derives, defaults, composes and invents no part** of
> the report. Where the body carries no `delivery`, no `delivery` reaches
> `converse_spoken`. Where it carries one the gateway cannot parse into a
> `SpokenDelivery`, the request is refused with a project-owned refusal carrying no
> input value and no chained cause, on ADR-0200 §9's stated ground for a refused
> recording. This is ADR-0177 §1's fourth clause satisfied, not widened: the report
> is the browser's own, and the one class the gateway supplies of its own remains
> the caller-owned deadline.

> **Normative.** The page reports the playback it last had in the air for the
> conversation it is sending, and reports nothing where it has none. It reports
> `COMPLETE` where the source ended of its own accord and `INTERRUPTED` where a press
> ended it — a distinction the front end already draws (`playbackInterrupted` against
> the `ended` listener in `playSpoken`) — and it invents neither.

> **Normative.** The report is derived from the decoded buffer the page already
> holds: its `duration` is `rendered`, and the elapsed playback time is `played`. No
> lane adds a second audio API, a media element, a `speechSynthesis` call or any
> other capability to obtain it; ADR-0200 §10's front-end clauses bind unchanged.

### 8. What this ADR does not decide

Each of these is deliberately open, and each names what would make it worth
deciding.

- **A fourth state for a rendering that never existed.** §4 leaves a degraded
  synthesis `UNKNOWN` rather than minting `NOT_RENDERED`. **Fires** when a stage
  needs to distinguish "nobody reported" from "there was nothing to report" —
  additively, since `SpokenDeliveryState` is a closed enum a later ADR may extend.
- **Delivery on any other channel.** A rendered reply on the page, a streamed one,
  a notification. Untouched: ADR-0130 §2 and ADR-0078 §8 keep delivery state off the
  notification records, and §3's absence clause means a text turn's row asserts
  nothing. **Fires** with a channel that can report and a consumer that needs it.
- **A bounded spoken channel's delivery.** ADR-0200 §11 defers the channel itself;
  its delivery arrives with it.
- **Verifying a report.** §2 refuses it outright on ADR-0099 §1's single principal.
  **Fires** on the day this hub has a principal distinct from the owner, which is
  the same condition several other refusals in the corpus wait on.
- **Barge-in and streamed speech.** ADR-0200 §11 defers both, and this ADR does not
  presuppose either: a report about a whole rendering is exactly what a non-streamed
  answer admits. **Fires** as ADR-0200 §11 says.
- **What the page does with an accidental press.** #1701's page-only resume of a
  held buffer is a sibling and is not this decision; a resume that never left the
  page produces no report, and §3's absence clause is what makes that legible.
- **Recording the channel a turn arrived on.** §3 forbids reading `delivery` as one.
  ADR-0200 §11 and ADR-0074 §11 keep the deferral and milestone 21 keeps the
  decision.

### 9. What the implementing lane owes

> **Normative.** The contract half lands as **one change**: `SpokenDelivery` and
> `SpokenDeliveryState` in `core/types.py` with §2's validator; the `delivery`
> argument on `converse_spoken`; the `delivery` member on `ConversationTurn`; the
> `record_delivery` operation and `append`'s new argument on `ConversationStore`;
> the `PROTOCOL_VERSION` bump; and — because `ConversationStore` gains a member —
> that Protocol's shared conformance suite and its canonical fake in
> `ai_assistant.testing` updated in the same change, which is `CONTRIBUTING.md` →
> "Adding a Protocol" applied to a widened one. **This is a breaking Protocol change
> and the lane flags it** (golden rule 5).

> **Normative.** The `orchestration` half owes: the local refusals of §1 and §2, the
> stamp before the turn plans, the `UNKNOWN` written at capture on this operation
> and on no other (§4), and the supplied fact reaching the composing stage off the
> tail `ConversationLifecycle.history` already read (§5) — with no second store call
> added on that path.

> **Normative.** The `interfaces/gateway/` half owes the fourth body member, its
> refusal path, and the page reporting §7's two states from the buffer it already
> holds. It adds no browser capability and no route.

> **Normative.** No file under `wire/` changes to carry the report beyond
> `PROTOCOL_VERSION` itself. `SpokenDelivery` is the shape the codec already carries
> — a frozen model of scalars, with `timedelta` on ADR-0087 §2e's duration form and
> a `StrEnum` as `SpokenAudioFormat` already is — so `wire/codec.py`'s `project`
> gains no branch, ADR-0087 §2c's scalar table gains no row, and `wire/surface.py`
> derives this argument's adapter from the annotation as it derives every other.

> **Normative.** The lane records this ADR on ADR-0200 and ADR-0074 only if this
> change did not — it did (§10), so the lane makes no header record and adds none.

Tests the lane owes, named so they are written rather than assumed: a report
against a conversation with no turns is discarded and the turn still runs; a second
report performs nothing; a report beside `conversation_id` `None` is refused before
any seam is called; an `UNKNOWN` argument is refused; a degraded synthesis leaves
`UNKNOWN`; the composing stage is told an `UNKNOWN` previous turn is unknown; the
supply path makes no second store call; and the captured episode's content is
byte-identical to what the same transcript produces with no report.

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

> **Normative.** This ADR **partially supersedes ADR-0200**, in ADR-0070 §3's sense,
> in exactly two scopes and no others:
>
> **(a) §3's argument count.** "It … takes four arguments and no others" becomes
> **five**, the addition being `delivery` and nothing else. Every other clause of §3
> binds unchanged, the audience clauses included.
>
> **(b) §10's body enumeration.** "carrying the **browser-owned** arguments of §3's
> signature and no others — `utterance`, `plays` and `conversation_id`" gains
> `delivery`, and "reads no fourth" becomes "reads no fifth". §10's `timeout`
> clauses, its one-route clause and its front-end clauses bind unchanged.

> **Normative.** This ADR **partially supersedes ADR-0074**, in the same sense, in
> exactly one scope: §9's enumeration of what `ConversationTurn` carries and what
> `ConversationStore` owes. The turn gains `delivery` and the store gains
> `record_delivery` and `append`'s new argument. §9's illustrative signature is
> illustrative by its own words — "the semantics above and below are the contract,
> the spelling is the lane's" — and nothing else in §9 or in ADR-0074 changes.

> **Normative.** Everything else about this ADR is additive under ADR-0082 §1: two
> new `core/types.py` names, one new argument on one method, one new operation on a
> non-promoted Protocol, and one new body member. No other ratified clause is read
> differently after it.

**Both records are made in this change**, under ADR-0082 §7's settled reading —
"§1's condition is that the superseding ADR **exists**, not that it is ratified" —
and in the shape ADR-0201 §8 and ADR-0200 §12 both used. ADR-0200's `Status` is
already a leading-token line, so this decision accumulates a second pair on it under
ADR-0070 §4's partial form without dropping ADR-0203's; ADR-0074's already carries
three pairs and accumulates a fourth. Each gains an appended dated note. Under
ADR-0082 §2 no amendment qualifier goes on either line — the note is the whole
record on a leading-token line. Neither scope parenthesis carries an `ADR-NNNN`
token, which is ADR-0070 §4's authoring constraint.

Four near misses, named so a reviewer can check them rather than take them:

- **ADR-0177 §1 is untouched.** Its enumeration counts *operations*, and this ADR
  adds none; its fourth clause admits every argument the promoted surface declares,
  and this one is the browser's own; its deadline carve-out is not widened, because
  the gateway supplies no part of the report. §7 states that as satisfaction rather
  than as a supersession, and ADR-0200 §12(a)'s arithmetic — thirty-one operations —
  is unchanged.
- **ADR-0200 §4 is untouched.** `SpokenTurn` gains no member: the report travels
  **in**, and nothing about the delivery of the answer this call produces is known
  by the time it returns. §4's four-member clause and its `spoken_degraded`
  biconditional stand word for word, and ADR-0203's partial supersession of §4's
  second-difference clause is neither widened nor narrowed.
- **ADR-0200 §8 is applied, not narrowed.** No audio is retained; two durations are
  not a rendering and permit none to be reconstructed. Its "adds no field to
  `EpisodicMemory`, no field to `Provenance`" clause is a statement about what
  ADR-0200 adds, and it stays true — this ADR adds none either (§3).
- **ADR-0130 §2 and ADR-0078 §8 are untouched.** Their refusal is about a
  notification candidate, its disposition and a held record, and about whether
  contact was attempted, reached a device, or was seen. This ADR adds no field to
  any of those types and says nothing about contact. `core/types.py`'s notification
  block stays byte-correct.

**No *amendment* record is owed anywhere.** ADR-0082 §1 owes one "when the later ADR
amends a named clause — and not otherwise". The two clauses of ADR-0200 and the one
of ADR-0074 that this ADR changes it **supersedes**, which is ADR-0070 §1's other
side and is recorded above; every other clause it touches it applies or satisfies.

## Consequences

**What becomes easier.** The assistant stops confidently building on words nobody
heard, which is the single most legible failure the milestone-19 phone pass found.
"Continue what you were saying" becomes answerable without a new intent, a new
route or a new operation — the composing stage gets one more fact and the existing
machinery does the rest. And the corpus gains a worked case of the ADR-0131 posture
on an output channel: delivery is something a device tells you, not something the
hub infers from having produced an answer.

**What becomes harder.** `converse_spoken` is now a five-argument operation and
`POST /ask/spoken` a four-member body, and both counts are ratified rather than
conventional, so the next addition costs another supersession. The conversation
index gains a member that is written on one operation and read on every one, which
is a small asymmetry a reader has to hold. And the page now owes a fact across two
round trips — it must carry the previous playback's measurement past the press that
ended it — which is state the front end did not previously keep between requests.

**What would trigger revisiting this.** Streamed speech (ADR-0200 §11) changes what
"played N of M" means, because there is no whole rendering whose duration is known
in advance; a report shaped for a complete buffer would need restating. A second
device playing the same conversation's answers would break §1's "the most recent
turn of this conversation" subject resolution, because two devices could report
about different turns — ADR-0074 §11's multi-spoke concurrency deferral is where
that lands, and it would take an explicit subject on the report. And a bounded
spoken channel (ADR-0200 §11) arrives with its own delivery question.

## Alternatives considered

**A field on `EpisodicMemory`, written at capture and updated by the report.** The
brief's recommendation, and the shape #1700 names first. It does not exist: ADR-0068
froze the record graph and `MemoryStore` has no update operation, so the value
capture writes is the value the record keeps forever — which is `UNKNOWN`, the one
value the report exists to replace. Making it work would mean retiring and
rewriting a record other records cite as evidence (ADR-0072 §3), which is a much
larger decision than this one and one this ADR has no standing to take.

**A companion record in the `MemoryStore`, keyed to the episode.** The other shape
that survives the freeze, and the one ADR-0130 §2's "what this ADR mints is the
record a delivery seam attaches to" suggests. Declined in §3: it puts a citable
record in the store the observer reads, it needs a retrieval nothing performs today
— a second read on the path ADR-0199 §5 and ADR-0203 §2 keep to one — and it
duplicates a relation the index already holds.

**A separate `report_delivery` member on the promoted surface.** #1700's second
candidate, and the better shape in exactly one case: the owner who interrupts and
never speaks again. Declined in §1 for two round trips against one, a second frame
per press under ADR-0084 §3's serial rule, a second gateway route against ADR-0200
§10's one, and a second refusal path — bought to make a record whose only reader is
a turn that never happens.

**Recording the previous turn's delivery on the *next* turn's episode.** Costs no
new store operation and no frozen-record problem, because the next episode is
written fresh. Declined: the fact is then keyed to the wrong turn, so a later turn
reading the interrupted episode alone still assumes it was heard — obligation 1's
"no later turn assumes the rest was heard" fails at the second remove — and it puts
channel-dependent text into a `content` that is replayed on every channel, which is
ADR-0197 §10's stated failure.

**Not recording it durably at all** — carrying the report only as far as this
turn's composing stage. Simplest, and it answers "continue what you were saying"
completely. Declined: obligation 2 asks for a recorded default of *unknown*, and a
fact that exists only during one call leaves the interrupted turn's episode
indistinguishable from a delivered one for every turn after the next.

**Recording the channel on the turn, so an absent `delivery` could be read
precisely.** It would resolve §3's one asymmetry — an absent value means "no spoken
rendering", which today is inferable but not stated. Declined because ADR-0200 §11
and ADR-0074 §11 defer exactly that to milestone 21, where the trigger and channel
are the fact being recorded, and taking it here would decide a milestone-21 question
as a side effect of a milestone-20 one.
