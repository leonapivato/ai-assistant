# 206. A notification is spoken where the poll asked and the placement admits, and a withheld one arrives unspoken

- Status: Proposed
- Date: 2026-08-28

## Context

### What milestone 20 asks for, and how little of it is open

`track:voice`'s milestone 20 is *proactive speech*, and its exit test is one
sentence: "a notification arrives as speech on an idle device, and a class the
owner ruled unspeakable deflects to an authenticated surface instead" (#1318,
`docs/roadmap.md`). Milestone 19 shipped everything a spoken *answer* needs —
two speech Protocols, a promoted operation that composes them, a browser that
records and plays, and a disclosure rule the composing stage applies. What
milestone 20 adds is one direction: the assistant says something nobody asked
for.

Four ratified decisions have already fixed most of the shape, and reading them
together leaves a much smaller question than the milestone sounds like.

- **ADR-0131 §1** rules that "a disposed notification reaches a device only as
  the **result payload of a request that device sent**", and that the request is
  `next_notification`. So there is no unsolicited frame to add, and speech
  changes nothing about *when* a notification travels.
- **ADR-0200 §2** rules that transcription, the turn, the disclosure ruling and
  synthesis "are composed in `orchestration`", and that "no adapter in
  `interfaces/` transcribes, synthesises, or sequences those stages". §10 adds
  that the front end "does not call `SpeechRecognition`,
  `webkitSpeechRecognition` or `speechSynthesis`, and no lane may wire one". So
  the rendering is the hub's, and it crosses the wire as audio.
- **ADR-0199 §3**'s fourth clause hands this ADR its central obligation by name:
  "No notification is placed as speakable on a channel of unbounded audience by
  this ADR. An ADR admitting a delivery channel of unbounded audience places what
  it places on the whole of §2's recorded origin for a notification —
  `NotificationCandidate.producer`, `notification_class` **and** `sensitivity` —
  and what it does not place stays withheld."
- **ADR-0199 §5**'s delivery clauses decide the withheld case before this ADR
  reaches it: such a delivery "is **not emitted on that channel**, and no
  deflection is spoken in its place", it "stays in the hub's durable outbox
  (ADR-0131 §3) and is delivered on a channel that can carry it **if and when a
  device asks on one**", and "Delivery on a channel of bounded audience is
  unaffected."

So what is genuinely open is narrow: **where the rendering is asked for**, **what
is placed speakable**, **what the page does with a rendering**, and **what
"idle" means** when the system holds no fact about the room.

### The tree, read rather than remembered

**One producer exists.** `orchestration/upcoming.py` is the only construction
site of a `NotificationCandidate` in `src/`, and every candidate it makes carries
three constants: `PRODUCER` is `"calendar-upcoming"`, `NOTIFICATION_CLASS` is
`"upcoming_event"`, and `sensitivity` is `DataTier.PERSONAL` — the last stated by
the producer and, in that module's own words, chosen because "the reader's
proposals over the identical content state the same tier, and a notification
carrying a weaker one would be the same content classified two ways". Its
`summary` is the belief's own rendered sentence and its `detail` is `None`,
"because the sentence is the whole of what this producer carries".

**The gateway fans one delivery out to many browsers.** `DeliveryFanOut`
(`interfaces/gateway/delivery.py`) holds one poll against the hub while at least
one `DeliveryStream` is open, and writes each answer to every open stream. Its
poll is `next_notification(acknowledging=acknowledging, budget=self._budget)` —
both arguments the gateway's own, no browser value among them. That is the fact
which decides §1's shape: there is one value and several readers, so nothing
about a rendering can be per-browser.

**The page already knows how to play, and already knows when it may not.**
`assets/app.js` holds one playback in the air (`playing`), ends it when a press
takes the record over, and decodes a hub-supplied rendering through the Web Audio
decoder rather than an `<audio>` element — because ADR-0168 §6's `media-src
'self'` "does not match a `blob:` or a `data:` URL". The decoding context is
built inside the press gesture, in `readyToPlay`, and resumed there. **That is
the single most consequential fact in this file for milestone 20**: a page that
has had no user gesture holds no running audio context, and a browser will not
give it one. A proactive utterance is therefore not something a page can
unilaterally produce, and §8 is written around that rather than against it.

### The two things that look open and are not

**The acknowledgement.** It is tempting to make a spoken delivery acknowledged
when playback ends — an interrupted playback would then not acknowledge, and
at-least-once would run to the ear rather than to the socket. ADR-0175 §5 has
already decided it the other way, in two marked clauses: "The gateway
acknowledges, on its next poll, a delivery it wrote to at least one open delivery
stream, and it acknowledges no other", and "A `delivery_id` never reaches a
browser… No browser acknowledges, retires, withdraws or dismisses a delivery."
Its prose states the cost and takes it: "past the gateway the guarantee is that
the notification was written to at least one stream, not that a person read it",
and closing that gap "would mean a browser holding the capability" ADR-0172 §1
closes its class against. §9 leaves it exactly there.

**Occupancy.** #1318's milestone-20 line says "occupancy-unknown is the default
posture, not the edge case", and it was written before ADR-0199. That ADR §4's
fourth clause now rules it outright — "Where occupancy is unknown, the posture is
the one that applies when the channel's audience is unbounded" — and its §4 prose
names milestone 20 as the reason. So there is nothing left here to decide: this
ADR consumes the rule and adds no signal it could be computed from.

### The one thing the milestone's own wording gets slightly wrong

The exit test says "a class the owner ruled unspeakable". ADR-0199 §3 makes
content withheld from an unbounded channel under **three** limbs — a record whose
`about_person` is stated, a class the owner recorded as unspeakable under §6, and
"any content of a class no ratified ADR has placed as speakable on such a
channel". The owner-record limb needs the surface ADR-0199 §6's last clause
defers and §9 lists with its firing condition, and this ADR does not build it.
The behaviour the exit test is after — a class that is not spoken, arriving on an
authenticated surface instead — is reachable through the third limb, which is
what §3 and §5 below use. Recording that the milestone's wording moved is better
than pretending the deferred surface is not deferred.

## Decision

We will let the polling device ask for a rendering, produce it inside the call
that answers the poll and nowhere else, place exactly one notification triple as
speakable, deliver a withheld notification unspoken with nothing audible marking
it, make "idle" a fact about the device rather than about the room, and leave the
acknowledgement precisely where ADR-0175 §5 put it.

### 1. The rendering is asked for on the poll, and produced when the poll is answered

> **Normative.** `AssistantEngine.next_notification` gains exactly one
> keyword-only argument, `plays`, a `tuple[SpokenAudioFormat, ...]` defaulting to
> the empty tuple. It is the formats the caller can render, in preference order,
> and it is the whole of what this ADR adds to that method's arguments.

The signature that describes, shown rather than marked (ADR-0089 §2):

```text
async def next_notification(
    self,
    *,
    acknowledging: Identifier | None = None,
    plays: tuple[SpokenAudioFormat, ...] = (),
    budget: timedelta,
) -> NotificationDelivery | None
```

> **Normative.** An empty `plays` asks for no rendering, and none is produced: no
> placement is decided, no synthesizer is called, and nothing about the poll's
> behaviour differs from what ADR-0131 §4 already fixes. A caller that cannot
> play audio omits the argument and is unaffected by every other clause of this
> ADR.

> **Normative.** A rendering is produced **inside the call that answers the
> poll**, after the entry has been selected, and never before. No entry is
> rendered in advance of a poll that asked for one, no rendering is retained
> between polls, and a redelivery of the same entry renders afresh.

> **Normative.** No rendering is written to the outbox, to any store, index,
> trail, trace, audit trail or log, in either tier. ADR-0200 §8's first clause
> binds this path in the terms it is already written in — "It exists in memory
> for the duration of the call and nowhere else. No setting enables retention and
> no configuration value can" — and this ADR adds no exception to it.

**An argument rather than a sibling operation, which is the opposite of what
ADR-0200 §3 did for the same question one surface over.** That section put a
spoken *turn* on its own member, `converse_spoken`, and its ground was that "a
channel's audience reaches the composing stage from the *operation the engine is
executing*". The ground does not transfer, and the reason it does not is
ADR-0199 §5's own: "A notification is not composed by ADR-0170's stage: ADR-0131
§1 rules that a delivery is 'the result payload of a request that device sent'
and ADR-0130 decides the artifact long before any device asks." There is no
composing stage here for an audience to reach. A spoken answer and a written one
are two different texts — §7 of that ADR makes `outcome.reply` *itself* the
deflection — so two operations were needed to compose two answers. A spoken
notification and a written one are the **same** `NotificationCandidate`: one is
rendered as audio and one is not, and nothing is composed differently either way.
A second operation would buy a second name for one artifact.

**And the fan-out settles it independently.** ADR-0175 §4 writes one delivery "to
**every** delivery stream open at the moment it returned, unchanged". A second
operation, or a per-browser format list, would ask the gateway to produce a
different value per reader — which it has one poll and one answer to do it with.
One value for every reader is what the carrier already is, so `plays` is one
value the *gateway* supplies, and §2 says so.

**Rendered at the poll rather than at disposition, for three reasons that each
suffice.** ADR-0200 §8 forbids audio in an outbox, so a pre-rendered entry has
nowhere to live. The great majority of entries are never polled by a caller that
can play them — the command line polls, and a browser with no running audio
context polls — so pre-rendering spends inference on renderings nobody hears.
And an entry can be delivered more than once (ADR-0131 §3's at-least-once, and
§4's per-delivery identifier), so "the rendering" is not a property of an entry
at all.

### 2. `plays` is the gateway's own value, and no browser argument reaches this poll

> **Normative.** On the gateway, `plays` is a value the gateway supplies of its
> own, fixed and identical on every poll. No browser request carries it, no
> browser value reaches it, and no browser narrows, widens or reorders it.
> ADR-0175 §6's second clause and ADR-0177 §1's second clause — "`next_notification`
> is the gateway's own poll, no browser request resolves to it, no browser argument
> reaches it" — bind unchanged.

> **Normative.** The gateway's `plays` names **every** member of
> `SpokenAudioFormat`, so no format the synthesizer can produce is excluded by the
> caller. Their order is a constant the gateway holds, set by the implementing lane
> from a recorded measurement of what browsers decode and changeable on a further
> measurement without an ADR. It is not derived from a `User-Agent`, from a
> capability a page reported, from which streams are open, or from anything a
> browser said.

> **Normative.** **One delivery carries one rendering in one format, and a browser
> that cannot decode that format is silent.** The engine picks the first member of
> `plays` the synthesizer's `formats` also names (ADR-0200 §3, unchanged), and the
> gateway has one poll and one answer for every open delivery stream (ADR-0175 §4),
> so there is no per-browser format to choose and no second rendering to send. A
> browser that could have decoded a member the engine did not pick plays nothing
> and renders the notification on the page, exactly as one that could decode
> neither does.

> **Normative.** That a browser played nothing is a **device fact**. No component
> reports it, records it, retries on it, or treats it as a disclosure outcome, and
> no clause of this ADR is conditioned on it.

**A browser-supplied format list is the shape a reader reaches for first, and it
is unavailable twice over.** ADR-0177 §1's second clause forbids a browser
argument reaching this poll at all — and even without that clause, ADR-0175 §4's
fan-out gives the gateway one answer for every open stream, so a list assembled
from two browsers with different capabilities has no value it could take.

**What naming the whole enumeration does and does not buy, stated exactly,
because the loose version of this sentence was wrong.** It guarantees that the
*synthesizer's* choice is never narrowed by the caller — whatever it can produce,
it may produce. It does **not** guarantee that every browser can play the result:
the engine picks one member (ADR-0200 §3), the gateway writes that one rendering
to every stream, and a browser whose decoder covers only the other member hears
nothing. Adversarial review found the overclaim on the second round, and the
clause above answers its question rather than softening it — such a browser is
**intentionally silent**, because the alternative is a per-stream answer this
carrier does not have. The exposure is bounded by `SpokenAudioFormat`'s own
membership, which ADR-0200 §9 confines to "IANA media types a browser can produce
with `MediaRecorder` without transcoding" and fixes at two members at this rung,
and it is paid where every other cost of a browser's capabilities is paid: the
notification is on the page either way.

**ADR-0177 §1's deadline carve-out is not widened, and the argument is worth
making rather than asserting.** That clause reads "The one class of argument the
gateway supplies of its own is a **caller-owned deadline**… On this surface the
class has exactly two members", and a reader could take it as forbidding the
gateway any non-deadline argument of its own. It does not, and the tree at this
ADR's base is what shows why: `DeliveryFanOut` already calls
`next_notification(acknowledging=acknowledging, budget=self._budget)`, where
`acknowledging` is a `delivery_id` that ADR-0175 §5 requires never to reach a
browser and therefore requires the gateway to supply of its own. So a non-deadline
gateway-supplied argument on this poll is ratified, shipped, and older than
ADR-0177. The clause is about the **deadline** class on the browser control
surface — the thirty-one operations §1's first clause enumerates, of which
ADR-0177 §1's second clause says `next_notification` "is not one" — and it names
this poll's budget because ADR-0175 §8's budget was the second shipped instance of
a gateway-chosen deadline, not to bring the poll under the browser surface's
argument rule. `plays` is not a deadline, so the class is unchanged; §11 records
that no header note is owed on ADR-0177.

### 3. What is placed as speakable, on the whole of the recorded origin

> **Normative.** This ADR is the ADR ADR-0199 §3's fourth clause names — the one
> "admitting a delivery channel of unbounded audience" — and it places on the whole
> of §2's recorded origin for a notification. **Exactly one triple is placed as
> speakable on a channel of unbounded audience:** a candidate whose
> `NotificationCandidate.producer` is `"calendar-upcoming"`, whose
> `notification_class` is `"upcoming_event"`, and whose `sensitivity` is
> `DataTier.PERSONAL`.

> **Normative.** Every other triple is withheld. That includes the same producer
> and the same class at any other `sensitivity`, every class of a producer this
> ADR does not name, and every producer that does not exist yet. No implementation
> reads this placement as reaching a tier, a class or a producer it did not name,
> and no lane widens it by resemblance.

> **Normative.** No placement here names `DataTier.SECRET`, which ADR-0199 §3's
> fifth clause forbids and which ADR-0130 §2 already refuses at validation, so no
> candidate carrying one reaches this path in any case.

> **Normative.** The placement is decided from those three recorded fields and
> from nothing else. No implementation decides it by reading
> `NotificationCandidate.summary`, `detail`, `references`, `goal_id`,
> `confidence`, or any other span of the content — not by keyword, not by
> pattern, not by a classifier, and not by asking a model. That is ADR-0199 §2's
> second clause applied at this supply site, and this ADR adds no exception to it.

> **Normative.** A candidate whose producer recorded no origin has no class and is
> withheld, on ADR-0199 §2's third clause. This path contains no route by which a
> candidate reaches it without those three fields, because
> `NotificationCandidate` requires all three; the clause is stated so that a later
> producer cannot be admitted here by a default.

**One triple, because one triple is what the tree can carry.** The placement is
the smallest set that makes the exit test's spoken half demonstrable, and it is
exactly the set `orchestration/upcoming.py` produces: three constants, none of
them derived from an entry's title, location or duration, which is the property
ADR-0130 §2 and ADR-0199 §2 both want of a value a disclosure rule keys on. The
calendar is also the class ADR-0199 §3 already placed on the *reply* path — "a
belief whose band is `ATTESTED` and whose `Attestation.reported_by` names the
calendar source ADR-0093 §7 configures" — so nothing becomes speakable here that
was not already speakable when the owner asked about it aloud. What changes is
the direction, and the direction is the whole of what this ADR is for.

**The tier is named and it is `PERSONAL`, which reads backwards against ADR-0199
§3's own worked example, so the difference is stated rather than glossed.** That
example is a producer whose tier varies with content — "'your build finished' and
'your build failed on the branch you pushed from the clinic' are the same producer
and the same class" — and the clause exists so that placing the `OPERATIONAL` one
does not admit the `PERSONAL` one. `calendar-upcoming` is not such a producer: its
sensitivity is a module constant, stated once, identical on every candidate, and
tied to the band the reader states over the same content. So there is no narrower
sibling here whose placement could be borrowed. There is one tier this producer
emits; it is placed; and a candidate from this producer at any other tier did not
come from the producer as built and is withheld, which is the fail-closed answer
rather than an inversion of the example.

**And that is what makes the withheld half demonstrable without inventing a
producer.** A candidate carrying `"calendar-upcoming"`, `"upcoming_event"` and
`DataTier.OPERATIONAL` is constructible today — the type admits it — and it is
withheld by the clause above. So the exit test's second half can be driven against
the producer the tree actually has, rather than against a fixture that exists only
to be refused.

> **Normative.** This ADR admits a **delivery-side supply for a channel of
> unbounded audience**, which is one of the components ADR-0204 §3's second clause
> names, and it states what that clause requires of one rather than settling the
> question by silence. The stamp test binds this path, and it binds it as a
> condition of the placement above rather than as a read performed at delivery.

> **Normative.** The producer placed above emits a candidate whose `summary` is
> derived from what a `Reader` proposed over a configured calendar source, and not
> from records of this store. ADR-0204 §5's last clause governs such a producer —
> "A producer whose inputs are not records of this store has nothing to inherit and
> writes `False`" — so nothing this ADR places as speakable can carry, or be derived
> from, a warrant `Provenance.supplied_withheld_content` stamps.

> **Normative.** That is a **condition of the placement and not an observation about
> it.** No ADR places as speakable on a channel of unbounded audience a producer
> whose inputs are records of this store without stating, in its own text, how
> ADR-0204 §3's test reaches this path for what that producer emits — over which
> records it is applied, and where. Until such an ADR exists no such producer is
> placed, and this section's withholding clause withholds it.

> **Normative.** No implementation satisfies that condition by resolving
> `NotificationCandidate.references` at delivery. The delivery path issues no store
> query, holds no `MemoryStore` and no `ContextProvider`, and reads no record.

**Why the obligation lands on the placement rather than on the delivery, and why
that is the stronger place for it.** ADR-0204 §2's evaluation is cheap because it
is a predicate over what a turn already holds — a few field reads per record over a
supply in hand — and it is explicitly one that "reaches no `ContextProvider` and no
`MemoryStore`, performs no second context assembly and no second retrieval, and
issues no store query of any kind". A delivery has nothing in hand: ADR-0130 §2
makes a candidate one that "references what it is about and does not contain it",
so a test over the records it references would be a fresh store read on a path that
has never had one, performed after an entry is leased and inside a budget §7
already bounds. And it would still not reach the value that is actually spoken,
because `summary` is free text the producer composed rather than a record this path
could test at all. The producer is where both problems disappear: it holds the
records, it writes the sentence, and ADR-0204 §5 already tells it what to inherit.
So the test stays where ADR-0204 §5 puts it, and what this ADR adds is the rule
that a producer which *could* carry a stamp is not placed until an ADR says how —
ADR-0199 §3's sixth clause and ADR-0204 §3's second clause pointing at one sentence.

### 4. What is spoken is the summary, byte for byte, and nothing composes it

> **Normative.** Where a rendering is produced, the text handed to
> `SpeechSynthesizer.synthesize` is `NotificationCandidate.summary` and nothing
> else. It travels **byte-for-byte**: no prefix, no announcement, no salutation,
> no punctuation added or removed, no case folding, no trimming, and no second
> value composed from it.

> **Normative.** `NotificationCandidate.detail` is **not** spoken, on any
> candidate, under any placement. It is delivered as it is today and rendered on
> the page.

> **Normative.** No model is called on this path and no stage composes anything.
> ADR-0170's composing stage has no subject here, and no lane adds one: an
> unprompted utterance is the producer's own sentence or it is nothing.

**Byte-for-byte because `summary` is already the sentence the user would be
told.** ADR-0130 §2 makes it so — "the summary and detail are the only free text a
candidate carries, and they are what the user would be shown rather than a copy of
a record" — and `orchestration/upcoming.py` takes it "as written rather than
re-rendered… That is what keeps the notification and the belief from disagreeing
about the same entry." A stage that prefixed "you have a notification" would be
composing an utterance no producer wrote and no disclosure rule ruled on, which is
the failure ADR-0200 §10 refuses `speechSynthesis` for, performed by us instead of
by the browser. It is also `NonBlankEncodableText` already, which is exactly what
`synthesize` requires, so nothing on this path constructs a text at all.

**`detail` is left on the page for a reason, and it is not squeamishness.** A
notification is an interruption, and ADR-0130's whole argument is that only a
perishable one earns one; an interruption that runs to a second paragraph has
stopped being an interruption. Speaking the one line and rendering the whole keeps
the page strictly more informative than the room, which is the direction every
clause of ADR-0199 §5 pushes and the direction a mistake here should fail in.

### 5. A withheld notification arrives unspoken, and nothing audible marks it

> **Normative.** Where the placement of §3 withholds a candidate, **no rendering
> is produced**: no synthesizer is called, nothing is spent, and the delivery
> carries no audio. That is ADR-0199 §5's clause taken as written — "not emitted
> on that channel, and no deflection is spoken in its place" — and this ADR adds
> no audible substitute of any kind, chime, tone or spoken notice included.

> **Normative.** The delivery is still returned by the poll, and the browser
> renders it on the page. ADR-0199 §5's "Delivery on a channel of bounded audience
> is unaffected" is what this discharges, and its clause that such a notification
> "stays in the hub's durable outbox and is delivered on a channel that can carry
> it **if and when a device asks on one**" is satisfied by the very request that
> asked: one poll serves both of that device's channels, so the withheld
> notification is delivered at once rather than waiting for a second one.

> **Normative.** **The rendered page the gateway serves to an admitted session is
> a channel whose audience is bounded**, and this ADR declares it. It is
> ADR-0199 §1's test satisfied on both limbs: what it emits reaches a person only
> by that person being positioned at and looking at a rendered surface, and the
> gateway holds the session fact ADR-0168 §3 and §6 tie that surface to. This
> declaration reaches this ADR's own subject — the delivery a poll returns — and
> declares the audience of no other channel.

> **Normative.** **The rendering is emitted on a channel whose audience is
> unbounded, always.** It is played out of a device into a room, which is
> ADR-0199 §1's "reaches whoever is within range of the device with no act of
> theirs". No caller supplies that audience and no value on this surface expresses
> it: `plays` says what the caller can render, not who can hear, and omitting it
> declines to open the unbounded channel rather than declaring a bounded one. No
> implementation, lane or later ADR reads a `plays`, a transport, a session or a
> device as raising this channel's audience from unbounded to bounded (ADR-0199 §8's
> third clause).

> **Normative.** ADR-0199 §5's last clause is satisfied on this path because
> **nothing here is composed for a channel of bounded audience.** A notification is
> not composed at all — ADR-0130 decides the artifact long before any device asks —
> so there is no value composed for a bounded channel that a fan-out could emit on
> an unbounded one. The rendering is produced for the unbounded channel and is the
> only value on this path produced for a channel at all.

> **Normative.** **The fan-out this ADR admits is not undifferentiated, and the
> differentiation happens at the hub rather than in the fan-out.** Whether a
> rendering exists at all is decided by §3's placement before any value leaves the
> hub, so a candidate this ADR withholds is fanned out with no audio in it. The
> obligation ADR-0199 §5's reasoning places on "whoever adds the speech" is
> discharged there, which is the earliest point on this path at which it can be.

> **Normative.** **Every destination of a rendering has the same audience.** A
> rendering is produced for a channel of unbounded audience and reaches only
> loudspeakers, each of which is such a channel, so ADR-0199 §5's last clause is
> satisfied on its second limb — the component "emits only on channels whose
> audience the value was composed for". There is no channel of bounded audience
> among a rendering's destinations for a fan-out to have to tell apart.

> **Normative.** **The stream value carries two emissions and they are not merged.**
> The delivery's own text reaches the page, a channel of bounded audience; the
> rendering reaches the loudspeaker, a channel of unbounded audience. Each is
> emitted on the audience it was produced for, neither is emitted on the other's,
> and no implementation reads the one carriage as putting either on the other's
> channel.

> **Normative.** ADR-0175 §4's "filters nothing… withholds nothing" therefore binds
> unchanged, and **this ADR requires no per-stream routing**: no browser-specific
> state at the gateway, no knowledge there of a page's decoder or its playback, and
> no stream selected over another. One delivery, one rendering, every open stream,
> unchanged.

**Two drafts of these clauses were wrong in two different ways, and both are worth
recording because the second correction is the one that reads the ratified prose
properly.** The first said the fan-out emitted "the rendering only where it will be
played", which the gateway cannot do: ADR-0175 §4 obliges it to write one value to
every open stream and forbids it filtering, and §2 and §8 forbid it the per-browser
state it would need. Architecture review found that on the fifth round. The second
answered by calling the gateway-to-page transfer a non-emission — which review
found again on the sixth, correctly: reclassifying a transfer does not change the
topology, and ADR-0199 §5's prose is explicit that "a channel of unbounded audience
may not be fed by an undifferentiated fan-out at all".

**What answers that sentence is where the differentiation sits, not what the
transfer is called.** Read with the marked clause it explains — a component "either
emits only on channels whose audience the value was composed for, or emits
nothing" — the prose's subject is a fan-out that cannot tell its destinations
apart *because they differ*, and its worked hazard, one paragraph up, is the
gateway relaying a value the hub composed for a screen. Neither is this path. The
rendering is composed for a loudspeaker and every destination is one, so the
clause's second limb holds exactly; and the decision that makes it hold — whether
a rendering exists — is taken at the hub, before the fan-out, which is precisely
where §5's prose says the obligation lands. A gateway that had to decide would be
the authoring golden rule 3 forbids, which is the outcome ADR-0175 §4 was written
to prevent and this ADR does not reach for.

> **Normative.** No signal about who is present enters this path. No occupancy,
> presence, diarization, speaker identification or paired-device evidence is read,
> computed, requested or reported, and none could change what is spoken if it
> were. ADR-0199 §4 binds whole, and its fourth clause — "Where occupancy is
> unknown, the posture is the one that applies when the channel's audience is
> unbounded" — is the posture this path is always in.

**"Deflects to an authenticated surface" is the exit test's phrase and this is
what it turns out to be.** There is no deflection *composed* here, because
ADR-0199 §5's silence clause forbids one: "Where nothing was addressed to the
assistant — a delivery, or any other emission on a channel nobody asked on — and §3
withholds the whole of what would be emitted, the outcome on that channel is
**silence**. Nothing is emitted announcing that something was withheld." What
"deflects to an authenticated surface" describes is the outcome rather than an
utterance: the notification reaches the owner on the surface the gateway
authenticated, and does not reach the room. A chime saying "there is something I
am not saying" is the one shape this section positively forbids, and §5's prose
gives the reason — an emission whose entire content is the existence of withheld
content, "delivered to a room that did not ask, with no answer to compensate it".

**The bounded-channel declaration is small and it is load-bearing.** ADR-0199 §8's
second clause gates shipping an unbounded channel on "a ratified ADR [having]
decided the surface by which a channel's audience reaches the composing stage",
and ADR-0200 §3 discharged that for the operation it added. On this path there is
no composing stage to reach, so what is owed instead is that the audience of each
emission be *declared* rather than computed — §8's third clause's requirement, met
here by two sentences in a ratified document rather than by a value anything
asserts. And without the bounded half stated, §5's "delivered on a channel that
can carry it" would name a channel no marked clause says can carry it. ADR-0200 §3's
prose already reads the page this way — "The rendered page is bounded: what it
emits reaches the owner through an act of theirs, looking at a surface the gateway
tied to the session it admitted" — but prose beside a mark supplies no obligation
(ADR-0089 §3), so the mark is made here where a rule depends on it.

### 6. What the poll returns, and where the line between withholding and degrading falls

> **Normative.** `NotificationDelivery` (`core/types.py`) gains exactly two
> members and no more: `spoken`, a `SpokenAudio | None`; and `spoken_rendering`, a
> `SpokenRendering`. Its `model_config` is unchanged — `extra="forbid"` and
> `frozen=True` — and ADR-0131 §4's reason for the first of those binds unchanged.

> **Normative.** `SpokenRendering` is a new closed `StrEnum` in `core/types.py`
> with exactly four members, whose serialized values are fixed here and are
> exactly these: `NOT_REQUESTED` is `"not_requested"`, `RENDERED` is
> `"rendered"`, `WITHHELD` is `"withheld"`, and `DEGRADED` is `"degraded"`. A
> lane adds a member only with an ADR deciding it; removing one, or changing one's
> value, is a change to what was decided and takes a superseding ADR.

**The values are named rather than left to the member names, and the reason is
the same one ADR-0131 §4 gives for spelling out `NotificationDelivery`'s
fields.** This enumeration crosses the wire inside a delivery, so two
implementations choosing `"withheld"` and `"WITHHELD"` would both conform to a
clause that named only the members and would not interoperate — "the
interoperability failure ADR-0084 §3 made framing and codec normative to
prevent, arriving one layer up". Fixing the values is also what makes the reserve
arithmetic below checkable: without them the longest value is unbounded, and a
conforming implementation could spend the margin ADR-0131 §4 left. The spelling
is `SpokenAudioFormat`'s and `DataTier`'s — the member name lowercased — so
nothing new is invented, and adversarial review found the gap on the first round.

> **Normative.** The four members are exhaustive and mutually exclusive, and each
> names one cause. `NOT_REQUESTED`: `plays` was empty, so no placement was decided
> and no synthesizer was called. `WITHHELD`: `plays` was non-empty and §3 withheld
> the candidate, so no synthesizer was called. `DEGRADED`: `plays` was non-empty
> and §3 placed the candidate, and speaking it did not complete. `RENDERED`: the
> rendering is in `spoken`.

> **Normative.** `spoken` is not `None` **exactly when** `spoken_rendering` is
> `RENDERED`, and a validator states that invariant in both directions.

> **Normative.** `spoken` is the rendering of `NotificationCandidate.summary` and
> of nothing else, and its `media_type` equals the format the engine asked for —
> the **first** member of `plays` that the synthesizer's `formats` property also
> names (ADR-0200 §1, §3). That the audio is an audible rendering of that text is
> the synthesizer's obligation, discharged in its conformance suite; no component
> decodes, re-transcribes or otherwise inspects a rendering to check it.

> **Normative.** `spoken_rendering` is `DEGRADED` in exactly four cases and no
> others: synthesis raised a `SpeechError`; the intersection of `plays` with the
> synthesizer's `formats` was empty; the rendering breached ADR-0200 §6's
> `hub_max_spoken_audio_bytes`; or the whole projected `NotificationDelivery`
> carrying that rendering would breach ADR-0085 §8c's payload limit. In every one
> the delivery travels without the rendering.

> **Normative.** **An elapsed budget is not among them.** §7 makes the rendering
> the request's own work in ADR-0135 §3's sense, so it is performed whatever the
> state of the budget and no implementation degrades on that ground. A synthesis
> that outlives the decorator's own deadline raises `SpeechTimeoutError`, which is
> a `SpeechError` and is the first case above.

**The empty intersection is discovered before a synthesizer is called rather than
reported by one**, which is ADR-0200 §4's own treatment of it — "discovered before
the call rather than reported by one, which is why nothing is spent on it" — taken
whole. It is the only one of the four that spends nothing.

**The list was five for two rounds and the fifth was a mistake of this ADR's own
making.** Architecture review found on the first round that an earlier §7 required
`DEGRADED` where the budget had run out and §6 did not admit it; the case was added,
and adversarial review then found on the sixth that the §7 clause creating the state
contradicted ADR-0135 §3. Removing the cause removed the case. Recording both steps
is worth more than presenting the four as though they had always been four.

> **Normative.** **A withholding is never reported as a degradation and a
> degradation is never reported as a withholding.** No implementation collapses
> the two, and none retries a `WITHHELD` delivery into speech on any subsequent
> poll, because the placement of §3 is a property of the candidate and not of the
> attempt.

> **Normative.** A failure to speak never fails the poll. A `SpeechError` out of
> `synthesize` — and nothing else — degrades under this section; **every other
> exception propagates unchanged**, so the stage catches `SpeechError` and does
> not catch `Exception`. That is ADR-0200 §4's translation rule at a second site
> and for its stated reason.

> **Normative.** A cancellation delivered while the poll is outstanding is
> neither a withholding nor a degradation. It propagates after cancellation-safe
> cleanup under ADR-0060's clause, exactly as it does on every other method of
> this surface, and it never sets `spoken_rendering`.

> **Normative.** ADR-0200 §8's authorship clause binds this path whole: no
> component on it writes an exception message it did not author, to either log
> tier, to a store, trail or trace, or into a surfaced error. What may be written
> for a synthesis failure is that it degraded and this project's own message for
> it.

**The degradation line is ADR-0200 §4's, and it lands the same way for the same
reason.** There, "a transcription failure **fails the call**; a synthesis failure
**degrades it**", because "a failure before there is [an answer] leaves nothing
worth returning, and a failure after there is one would throw away an answer the
user already has". Here there is never a stage before the answer: the notification
exists, has been disposed, and has been leased. A poll that raised because a
synthesizer failed would spend an entry's lease on a fault, and the owner would
see the notification later or not at all — losing a notification to a speech
engine, which is precisely what ADR-0131 §3's durability exists to prevent.

**A closed enumeration rather than ADR-0200 §4's boolean pair, and the difference
is not aesthetic.** `SpokenTurn` carries `spoken_degraded` beside `heard`,
`outcome` and — since ADR-0205 §1 — `episode_id`, which between them already
distinguish every shape that surface admits; and on it there is no disclosure fork
at all, because ADR-0200 §7 makes
`outcome.reply` *itself* the deflection. Here there are four states and one of
them — the withholding — must never be confusable with a fault. A fault invites a
retry, and a withholding retried is a disclosure rule defeated by a loop. Two
booleans would admit two combinations a validator would then have to forbid; an
enumeration admits none, and the member names are what the gateway logs and what a
hub-side test reads — the page is given the rendering alone (§8).

**`SpokenRendering` is not `SpokenDeliveryState`, and no lane merges them.**
ADR-0205 §2 mints a closed `SpokenDeliveryState` — `UNKNOWN`, `COMPLETE`,
`INTERRUPTED` — for what a **device reports** about a spoken answer it played. This
enumeration is about what the **hub produced** for a delivery nobody asked for, and
nothing on this path reports anything back (§9). Neither is derivable from the
other and the two never appear on one value: `RENDERED` says the audio left the hub
and says nothing about whether it was heard, which on this path is precisely the
question ADR-0205 §8 leaves open. Its own first deferral — a fourth state "for a
rendering that never existed", firing "when a stage needs to distinguish 'nobody
reported' from 'there was nothing to report'" — is a distinction this enumeration
already draws, because it has no report to be confused with.

**Why the delivery reserve ADR-0131 §4 fixed does not have to move, with the
arithmetic so a reviewer can check it rather than take it.** That section forbids
delivering a candidate whose canonical encoding exceeds the contract limit "less a
256-byte delivery reserve", covering a wrapper it computed at "130 bytes at most:
34 structural… plus at most 96 for the identifier". The two members above add, in
ADR-0087 §2's canonical form, `,"spoken":null` — 14 bytes — and
`,"spoken_rendering":"not_requested"` — 35 bytes, taking the longest of the four
values the clause above fixes, which is what makes the figure a bound rather than
an example. That is 49 bytes, for a worst case of 179 against a reserve of 256,
with 77 bytes still in hand. **So the reserve stands and is not superseded**, and
`offer`'s refusal is unchanged.

**The rendering is what does not fit in a reserve, which is why it degrades
instead.** `hub_max_spoken_audio_bytes` defaults to 512 KiB of decoded audio,
about 683 KiB base64-encoded on ADR-0200 §6's own 4:3 arithmetic, and no reserve
of any size accommodates that. So the fourth degradation case above measures the
**whole projected result** and drops the rendering, which is ADR-0200 §4's fourth
case reaching a second surface. **The second measurement that section needs has no
subject here**: a delivery with `spoken` `None` is the value ADR-0131 §4's reserve
already guarantees fits, as the arithmetic above shows, so a rendering-free
delivery cannot be over §8c and there is nothing further to drop.

### 7. The budget bounds the waiting, and the rendering is the request's own work

> **Normative.** `budget` bounds how long the hub may wait for an entry and bounds
> nothing else about the request. **ADR-0135 §3 binds this poll unchanged**, in the
> terms it is written in: the request's own work "run[s] to completion whatever the
> state of the budget, and a request whose own work outruns its budget has broken
> no rule", and "an elapsed budget is no ground for withholding a delivery that
> selection produced".

> **Normative.** **The rendering is the request's own work in that clause's sense.**
> It is performed after the selection step, it runs to completion whatever the state
> of the budget, and no implementation declines it, shortens it or degrades it on
> the ground that the budget has elapsed. A poll may therefore answer later than
> `budget`, and does so by construction whenever it renders.

> **Normative.** The rendering's bound is the deadline decorator the composition
> root wires over the synthesizer (ADR-0200 §1) and nothing else. Expiry there is a
> `SpeechTimeoutError`, a `SpeechError`, so §6's first degradation case governs it.

> **Normative.** ADR-0131 §4's `budget` clauses bind unchanged: the closed range
> from zero to `hub_max_notification_budget`, the refusal rather than a clamp
> outside it, and the immediate poll at zero — which, under ADR-0135 §3, selects at
> once and then does the request's own work, so a zero budget renders exactly as any
> other budget does where a rendering was asked for.

> **Normative.** ADR-0131 §4's ordering rule binds unchanged and comes first: a
> request whose arguments are refused has no effect on the outbox, and arguments are
> validated "before the acknowledgement is applied, before any entry is selected,
> and before any other outbox state changes". A malformed `plays` is such an
> argument, and no rendering is attempted on a request whose arguments were refused.

**An earlier draft made `budget` bound the whole call, and it contradicted a
ratified clause nobody had read.** It threaded the caller's remaining budget into
the synthesis stage on ADR-0200 §3's rule, so an entry arriving near the window's
edge degraded for want of time. Adversarial review found on the sixth round that
ADR-0135 §3 had already decided this exact question the other way — a poll's budget
"bounds **how long the hub may wait for an entry to become available**, and bounds
nothing else about the request" — and that the draft would have partially superseded
it without saying so. ADR-0135's semantics are adopted rather than superseded, and
the ADR is strictly better for it: the fifth degradation case disappears, the
reserve deferral disappears, and a notification that arrives at the end of a poll
window is spoken like any other.

**Why ADR-0200 §3's threading rule does not transfer, stated because the two look
alike.** There, `timeout` is "the budget for the whole call — transcription, the
turn and synthesis together", because a caller pressed a button and is waiting for
an answer; the deadline is ADR-0029 §4's caller-owned one and every stage is inside
it. Here the caller asked "have you anything for me", the hub has already answered
that question by selecting an entry, and what follows is work on a delivery the
outbox has already leased. ADR-0135 §3 is the clause that names the difference, and
it names it for the acknowledgement and the selection before this ADR adds a third
item to the same list.

**What this does to ADR-0175 §4's cadence, and where the answer is.** That clause
has the gateway writing on every open delivery stream "at least once per
`gateway_notification_budget`", and a poll that renders answers later than its
budget. So a gateway that wrote only when a poll returned would breach the cadence
by up to the synthesis bound, and §8 is where this ADR stops it doing that: the
keep-alive is paced by the interval and not by the poll, so the clause is satisfied
literally, in the two value kinds it already fixes, on every stream and at every
budget.

**An earlier draft argued the cadence was merely *bounded* and that this was
enough, and both lenses blocked it on the seventh round.** That draft leant on
ADR-0135 §3's record that "a poll's occupancy was never exactly its budget" —
argument validation, the acknowledgement and the result frame's write all sit
outside the waiting — and called a rendering a larger term in a sum that was never
zero. The reasoning does not hold and the ADR is better without it: ADR-0135's
slack is microseconds of bookkeeping, a rendering is seconds of synthesis, and
"bounded by the budget plus the synthesis ceiling" is a weaker guarantee than "at
least once per `gateway_notification_budget`", which is what §4 actually says. A
clause is satisfied or superseded; there is no third thing, and this ADR
supersedes neither ADR-0175 nor ADR-0135. §8 satisfies it and §11 records the
reading.

### 8. The page is given the rendering, the keep-alive does not wait for the poll, and an idle device is a fact about the device

> **Normative.** The value the gateway writes on a delivery stream gains **exactly
> one member**, `spoken`, and no other. `streams.notification`'s enumeration is
> otherwise unchanged — `kind`, `notification_class`, `summary` and `detail` — and
> every member it drops today it still drops.

> **Normative.** `spoken` is `null` wherever `NotificationDelivery.spoken` is
> `None`, and otherwise an object carrying exactly two members, `content` and
> `media_type`, projected from that value. There is no third shape and the member
> is never omitted, so a page reads one key rather than testing for a key's
> presence.

> **Normative.** `spoken_rendering` does **not** cross to a browser. The page's
> behaviour turns only on whether a rendering arrived and on the two device facts
> below, so a member carrying *why* one did not would be a value nothing on the
> page acts on, and `streams.notification`'s enumeration is closed against exactly
> that. It stays on `NotificationDelivery`, where the gateway logs it and a
> hub-side test reads it.

> **Normative.** `delivery_id` still never reaches a browser, and neither do the
> confidence, the sensitivity or the references that projection drops today.
> ADR-0175 §5's third clause binds unchanged, and this ADR adds no member by which
> a browser could acknowledge, retire, withdraw or dismiss anything.

**The projection had to be decided here because it is a closed enumeration and a
lane may not widen it on its own.** `streams.notification`'s own docstring says
"**The enumeration is the point** … what may reach the page is decided here rather
than by whatever a `NotificationCandidate` happens to carry", and §12's last
clause forbids a lane adding a deliverable this ADR does not name. So a rendering
the page never receives is a page that cannot play, and adversarial review found on
the fifth round that §8 required a behaviour no clause supplied the input for.
Naming one member rather than two is the same discipline that enumeration already
applies to `confidence`, `sensitivity` and `references`.

**And the value on a stream gets much larger, which ADR-0175 §4 already absorbs.**
A rendering is up to `hub_max_spoken_audio_bytes` of audio, about 683 KiB base64
on ADR-0200 §6's arithmetic, where a delivery value today is a few hundred bytes.
ADR-0175 §4 already holds "at most one value pending per stream" and already ends
a stream whose write has not completed when the next value is due, "so a browser
that stops reading cannot delay another browser's delivery" — which is the clause
that prices this, unchanged, and costs the abandoned browser a reconnect.

> **Normative.** The gateway writes on every open delivery stream at least once per
> `gateway_notification_budget` **whether or not a poll has returned**. Where that
> interval elapses while a poll is still outstanding — which a poll that renders
> may cause (§7) — the gateway writes "a value carrying nothing but its own kind".
> ADR-0175 §4's cadence clause is thereby satisfied literally, in the second of the
> two value kinds it already fixes, and is neither superseded nor relaxed.

> **Normative.** The keep-alive is paced by that interval and never by the poll's
> return. A write of either kind restarts the interval, so a gateway whose polls
> complete within their budget writes exactly what it writes today and at exactly
> the cadence it writes it at today; a keep-alive is emitted only where a poll has
> outrun the interval, which before this ADR could not happen.

> **Normative.** **A delivery and a keep-alive never contend, and the delivery
> wins.** Restarting the interval discards any keep-alive already due, already
> scheduled or in flight for it: where a poll returns as the interval elapses, the
> delivery **is** that interval's write and no keep-alive is written beside it.
> An implementation serialises the two rather than letting both offer a value, so
> no stream is ever abandoned under ADR-0175 §4's pending-value clause on account
> of a keep-alive falling due beside a delivery that did not delay it.

> **Normative.** That write is the gateway's own, on ADR-0175 §4's terms and
> nothing more: it carries no part of any notification, is not a delivery, is
> acknowledged by nothing, and leaves ADR-0175 §5's acknowledgement rule and this
> ADR's §9 exactly where they stand. It composes no behaviour the promoted surface
> does not offer (ADR-0168 §1) — the gateway already emits this value of its own
> motion whenever a poll returns nothing — so what this section changes is **when**
> it is written and not **what** is written.

> **Normative.** ADR-0175 §4's per-stream rules bind the keep-alive unchanged: the
> gateway holds at most one value pending per stream and queues nothing behind one,
> and a write that has not completed when the next value is due on that stream is
> abandoned and that stream ended. A keep-alive is a value due on that stream, so a
> stream stalled behind a rendering meets that clause exactly as it meets it behind
> any other value, and this ADR does not soften it.

> **Normative.** **The keep-alive's lifetime is the fan-out's and not the poll's.**
> It exists while and only while at least one delivery stream is open; it is
> dropped in the same step that ends the last stream and in the same step that ends
> them all on the way down; and nothing of it survives that step — no timer, no
> task, no pending write, and no value written on any stream afterwards. Whatever an
> implementation schedules it on is released or cancelled there, observably, beside
> the poll and never instead of it.

**That clause is stated because the mechanism it constrains does not exist yet and
the one beside it would not cover it.** `DeliveryFanOut._reap()` today cancels one
thing, the poll, and `close`, `shutdown` and the re-open path all reach the fan-out's
end through it; an implementation that hung the keep-alive off a second task and
left `_reap` as it stands would leave that task alive with no stream to write to.
The two clauses that forbid that outcome already bind the gateway and are not
weakened here: ADR-0175 §4 holds a poll "**while and only while** at least one
delivery stream is open" and "holds no poll at any other time", and §5 rules that
"when the last delivery stream ends, the gateway closes its delivery connection".
A keep-alive outliving the last stream would be the gateway holding, of its own
motion, a thing that writes to browsers after the condition for writing to them has
gone — which is also the shape ADR-0060 §1 names when it lists "a spawned task"
among what a cancellation must not orphan, stated there for the Protocol surface
and reached here by the same reasoning rather than by extension of its scope.
Adversarial review found this on the eighth round, against the clauses above as
they were first written.

**One figure still paces both, which is the clause a reader will check next.**
ADR-0175 §8 rules that `gateway_notification_budget` is both the poll's `budget`
and "the interval within which §4 obliges a write on every open delivery stream",
and that "one figure paces both". This ADR adds no second figure and no heartbeat
setting: the keep-alive interval **is** that field, so §8's refusal of a second
clock — "a heartbeat shorter than the poll obliges a write with nothing to write
about, and one longer is inert" — has nothing to bite on here. What §8's own
reason-clause observes, that "the write a browser observes is the completion of the
poll the budget bounds", stated the mechanism of a gateway whose polls could not
outrun their budget; §7 creates the case where one can, and pacing the keep-alive
by the same figure is what keeps §8's obligation true in that case rather than
letting it lapse. A reader holding only ADR-0175 sets the same field to the same
default and observes the same cadence.

**The two writes are serialised because the abandonment clause is unforgiving and
correct to be.** ADR-0175 §4 ends a stream whose pending write has not completed
when the next value is due, and a delivery is up to 683 KiB where a keep-alive is a
few bytes — so a stale tick arriving behind a delivery would end a healthy stream
in the instant after it was given the notification it was waiting for, costing a
reconnect for a liveness signal the delivery had just supplied. The clause above
removes the contention rather than softening the abandonment: nothing about §4's
rule changes, and what changes is that the gateway never offers a second value it
did not need to. Adversarial review found this on the ninth round.

**And the keep-alive matters most in exactly the state this ADR creates.** §4's
own ground for it is that "a stream that writes nothing for an hour is a stream
nothing can distinguish from one that has died, at either end", and a browser
holding a delivery stream cannot tell a gateway waiting on a long synthesis from a
gateway that has stopped. Tying the keep-alive to the poll's return would have made
this ADR's one new source of delay the one condition the keep-alive could not
report — which is the failure §4 spends a write to prevent, met head on.

> **Normative.** "Idle", for the browser this milestone speaks from, is a
> conjunction of facts about the **device** and never about the room: the page
> holds a running audio context established by a user gesture in this document,
> and it holds no playback in the air. It is not an audience fact, and no clause
> of this ADR is conditioned on who is present or on whether anyone is.

> **Normative.** The page plays a rendering only while both hold. Where either
> does not — no running context, or a playback already sounding — it plays
> nothing and renders the notification on the page.

> **Normative.** A rendering the page does not play is **dropped**. The page holds
> no rendering for later, queues nothing behind a playback, and plays no
> notification after the delivery that carried it has been rendered on screen.

> **Normative.** A rendering never interrupts a playback in the air, and a press
> to talk always interrupts a notification's playback. Nothing in this ADR
> weakens ADR-0200's push-to-talk path or the interrupt the page already
> performs; a notification is the interruptible one of the two.

> **Normative.** None of the facts above is reported to the gateway or to the
> hub. No component sends, records or infers whether a page had a context, was
> playing, played, finished playing or was interrupted, and no clause of this ADR
> is conditioned on any of them.

**The audio context is the constraint that decides this section, and it is a
property of browsers rather than of this design.** `assets/app.js` builds and
resumes its decoding context inside the press gesture, in `readyToPlay`, because
that is the only place a browser will let it; a page that has had no gesture since
load holds no running context and cannot make one. So an unprompted utterance is
possible exactly on a page the owner has already spoken to, and the honest
statement of the milestone is that the device speaks *proactively* rather than
*spontaneously*. Stating it as a device fact is also what keeps it out of ADR-0199
§4's way: a page that cannot play is not evidence about a room, and it must never
become a reason a rendering was or was not produced.

**Dropping rather than queueing, which is ADR-0175 §4's discipline one hop
further out.** That section rules that "the gateway retains no notification", that
"a delivery stream opened after a delivery was written carries no replay of it",
and that it "holds at most one value pending per stream and queues nothing behind
one". A page that held renderings would be the buffer ADR-0175 §4 refuses,
rebuilt in JavaScript, bounded by nothing, and aging against an artifact ADR-0130
says is about a moment — "something that keeps is not an interruption, it is a
message". The notification is not lost by dropping the audio: it is on the page,
which under §5 is the channel that carries it.

**And the interrupt direction is chosen rather than inherited.** A press is the
owner addressing the assistant, and ADR-0199 §5's asymmetry — an addressed turn
always answers, an unaddressed emission stays silent — is the same asymmetry seen
from the playback side. The utterance nobody asked for yields to the one they did.

### 9. The acknowledgement does not move, and this path reports nothing about the room

> **Normative.** ADR-0175 §5 binds unchanged. The gateway acknowledges, on its
> next poll, a delivery it wrote to at least one open delivery stream and
> acknowledges no other; a `delivery_id` reaches no browser; and no browser
> acknowledges, retires, withdraws or dismisses a delivery. Playback is **not** an
> acknowledgement, and an interrupted, dropped, unplayed or undecodable rendering
> changes nothing about what is acknowledged or when.

> **Normative.** No lane cites this ADR toward moving the acknowledgement to
> playback, toward a playback report from a browser, or toward any value by which
> a device tells the hub what it played.

> **Normative.** ADR-0078 §8's refusal binds unchanged, in the terms
> `core/types.py` already carries: whether contact was attempted, reached a
> device, or was seen is not a field of a candidate, of a disposition or of a held
> record, and this ADR places none there. `spoken_rendering` is a fact about a
> **delivery attempt's rendering** and lives on `NotificationDelivery`, which is
> the seam's own value and not a stored record.

> **Normative.** Whether a spoken *answer's* delivery is a fact the device reports
> is **ADR-0205's** subject and is not decided here. Its §8 leaves "delivery on any
> other channel… a notification" open by name, firing "with a channel that can
> report and a consumer that needs it", and this section neither decides that
> question nor refuses it: ADR-0205's subject is a turn the owner asked for, and
> this ADR's is a delivery nobody asked for.

**Moving the acknowledgement is the most tempting change this ADR could make and
it is the one ADR-0175 §5 has already priced.** The appeal is real: a notification
spoken over is a notification the owner did not hear, and at-least-once that
stopped at the ear would redeliver it. The price is stated in §5's own prose and
does not change because the delivery is audio. A browser reporting playback needs
either the `delivery_id` — "a credential this system minted, held in a browser,
spendable against the hub", which ADR-0172 §1 closes its class against — or a
gateway holding the token "for a period bounded by nothing the gateway controls,
because a browser may never come back". Neither is worth a duplicate this system
already tolerates by design: ADR-0131 §3's guarantee is at-least-once, and the
owner seeing one notification twice is that guarantee working.

**ADR-0205 is the contrast that makes this refusal legible rather than merely
conservative.** A spoken answer's delivery is reportable because `converse_spoken`
has a next call to carry the report: ADR-0205 §1 puts it on that call precisely so
that it arrives "with the next press, in the round trip that already exists, and
reaches that stage without a second frame, a second admission, a second refusal
path or a second gateway route". A notification's playback has no such round trip.
The gateway's poll loop is the only one, ADR-0175 §5 has already ruled what rides
it, and its write-then-disconnect arm is the case where there is no next poll at
all. So the two decisions differ because their carriers differ, not because one is
more cautious than the other — and ADR-0205 §8's second deferral says so from its
own side.

**And the fact would have nowhere true to live.** ADR-0078 §8's refusal is not
incidental; it is the reason ADR-0130 §2 states "A candidate carries no delivery
state" and the reason ADR-0131 keeps transport state in the outbox rather than on
the artifact. A playback report would be delivery state arriving from the far side
of a fan-out that cannot tell two browsers apart (ADR-0175 §5's fourth clause), so
the hub would be recording that "a device" played something without being able to
say which, or how many did not.

### 10. Deferred, by name, each with the condition that fires it

- **A bound on how far a rendering may push a poll past its budget** (§7).
  ADR-0135 §3 permits the request's own work to outrun the budget and this ADR
  adds a term to it; the ceiling today is the synthesis decorator's own deadline,
  which a deployment sets. **This deferral no longer touches ADR-0175 §4's
  cadence**, which §8 preserves whatever the poll does; what is left open is how
  long a *notification* may take to arrive once the hub has one, which is a
  latency question and not a liveness one. **Fires** on a measurement that a
  browser waits long enough for a delivery to matter to the owner — a figure the
  implementing lane can produce and this ADR cannot.
- **Streamed speech on the delivery path.** The rendering comes back whole, as
  ADR-0200 §11 already defers it for a turn. **Fires** with that deferral, which
  it presupposes: a streamed delivery needs a streamed rendering first.
- **A rendering for a channel of bounded audience** — a worn earpiece, ADR-0199
  §1's own example. §5 declares this path's rendering unbounded outright and admits
  no value that could say otherwise. **Fires** with the first device satisfying
  ADR-0199 §1's bounded test, or with the spoke surface ADR-0094 §10 defers,
  whichever comes first, and it arrives as its own declared channel rather than as
  an argument here.
- **The surface carrying ADR-0199 §6's "may be spoken" records.** §3's placement
  is the whole of the posture until it exists, exactly as ADR-0199 §9's second
  deferral says. **Fires** with the first posture the owner wants that differs
  from §3's placement — this ADR does not build it and the milestone-20 exit test
  does not need it (Context, last subsection).
- **A second rendering, or a per-browser one** (§2). One delivery carries one
  format, so a browser whose decoder covers only the other member is silent.
  **Fires** on a measurement that a browser the owner actually uses cannot decode
  the ordered first format — at which point the cheap remedy is reordering the
  gateway's constant, which §2 admits without an ADR, and the expensive one is a
  carrier that answers per stream, which is one.
- **A second notification producer's posture.** §3's second clause withholds every
  triple it does not name, and ADR-0199 §3's sixth clause already obliges the ADR
  admitting a producer to state its posture. **Fires** with that producer.
- **Playback as a reported fact** (§9). **Fires** as ADR-0205 §8's second deferral
  says — "with a channel that can report and a consumer that needs it" — and it
  needs a home for delivery state that is not a candidate, a disposition or a held
  record, which ADR-0078 §8 refuses and this ADR does not reopen.
- **A placed producer whose inputs are records of this store** (§3). ADR-0204 §3's
  stamp test has no subject on this path while every placed producer's inputs sit
  outside the store, which is a property of the placement rather than luck.
  **Fires** with the first ADR that would place such a producer, which owes the
  statement §3 requires of it before it may.
- **A page that speaks with no prior gesture** (§8). Not deferred so much as
  unavailable: it is a browser's rule, not ours. **Fires**, if ever, at
  milestone 21's native spoke, which holds its own audio device.

### 11. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?

> **Normative.** This ADR **partially supersedes ADR-0131**, in ADR-0070 §3's
> sense, and supersedes nothing else wholly or partially. The scope is exactly two
> clauses of ADR-0131 §4 and no other clause of that ADR or of any other:
>
> **(a) §4's method declaration.** The signature it fixes gains one keyword-only
> argument, `plays`, defaulting to the empty tuple, and gains nothing else. Every
> other clause §4 places on that method binds the amended signature exactly as it
> binds the original — the keyword-only convention, the budget range and its
> refusal, the ordering of validation before effects, and the rule that no
> argument carries a device identity.
>
> **(b) §4's `NotificationDelivery` declaration.** The model "declared exactly as
> below" gains exactly two members, `spoken` and `spoken_rendering`, and gains
> nothing else. Its `model_config` is unchanged and §4's reason for `extra="forbid"`
> binds unchanged.

**Both are supersessions rather than stacked additions because §4 declares
closed shapes.** A reader holding only ADR-0131 builds a method with two arguments
and a model with two members, and a peer built that way and a peer built from this
ADR do not interoperate — which is ADR-0070 §1's first limb without argument.
Calling either an amendment would be the mis-declaration ADR-0082 §1 warns of.

**Adding the member bumps `PROTOCOL_VERSION`**, on ADR-0124 §9's rule as
`wire/envelope.py` records it, and §12 puts that obligation on the lane that makes
the change.

Six near misses, named so a reviewer can check them rather than take them:

- **ADR-0131 §4's 256-byte delivery reserve is untouched.** §6's arithmetic shows
  the two new members cost 49 bytes against 77 bytes of margin, so a reader holding
  only ADR-0131 computes the same ceiling and `offer` refuses the same candidates.
  Had the figure moved, this would have been a third scope item and would have said
  so.
- **ADR-0131 §1, §2, §2a, §3 and §3a are untouched.** Delivery is still the result
  payload of a request the device sent; the delivery connection still carries one
  request; the outbox, the lease, the at-least-once guarantee and the
  per-delivery identifier are all read and used as given. A reader holding only
  them builds the same seam.
- **ADR-0130 gains and loses no sentence.** §3's placement reads `producer`,
  `notification_class` and `sensitivity` — three fields ADR-0130 §2 put on the
  candidate — for a purpose it did not name and does not exclude, which is exactly
  what ADR-0199 §10 already recorded of its own reading of the same three fields.
  §4 speaks `summary` and leaves `detail`, both of which ADR-0130 §2 makes "what the
  user would be shown"; §9 restates §2's "A candidate carries no delivery state"
  rather than moving it. A reader holding only ADR-0130 produces the same artifact,
  so **no record is owed on it**.
- **ADR-0199 is consumed and discharged, not touched.** §3 places on the whole of
  the recorded origin its §3's fourth clause names; §5 takes its §5's delivery
  clauses as written and adds the audience declarations its §8 asks an admitting
  ADR for; §4 binds whole and unweakened. Every rule of it binds this path exactly
  as ratified and this ADR reads none of them more widely, which is ADR-0200 §12's
  finding about the same ADR reached again on the delivery path. **No record is
  owed on it.**
- **ADR-0175 §4, §5, §6 and §8 are untouched, and the one a reader will doubt is
  §4's cadence.** Its fan-out clause is satisfied by the gateway relaying one value
  unchanged and is argued in §5 rather than asserted; its retention clause binds
  unchanged (§8); §5's acknowledgement rule is left exactly where it stands (§9);
  §6's second clause — that this poll is the gateway's own — is what §2 depends on
  rather than what it changes, and its closed enumeration of five browser-reached
  operations gains nothing, because this ADR adds no browser-reached operation.
  **The cadence clause is the one to check**, because §7 lets a poll that renders
  answer later than `gateway_notification_budget`. It is satisfied rather than
  weakened, and §8 is where: the clause obliges a write per interval of one of two
  kinds — "a delivery where the poll returned one, and otherwise a value carrying
  nothing but its own kind" — and §8 makes the gateway write the second kind when
  the interval elapses with a poll still outstanding. The obligation is met on its
  own words, at its own figure, on every stream and at every budget. **No record is
  owed on ADR-0175**, and none would be enough if one were: a clause satisfied
  literally is not amended, and a clause a later ADR could not satisfy would need
  superseding rather than recording — which this lane's fence would not have
  admitted. §8 also checks the second clause a reader reaches from there, ADR-0175
  §8's "one figure paces both", and adds no second clock.
- **ADR-0135 §3 is adopted rather than superseded, and §7 was rewritten to adopt
  it.** Its clause that a poll's budget bounds "how long the hub may wait for an
  entry to become available, and bounds nothing else about the request" is read as
  written and applied to the rendering, which is the request's own work in exactly
  the sense §3 gives the acknowledgement and the selection. Its zero-budget
  reading, its elapsed-budget selection rule and its refusal to let a budget
  withhold "a delivery that selection produced" all bind unchanged, and a reader
  holding only ADR-0135 builds the same poll. **No record is owed on it**, and the
  draft that would have owed one is recorded in §7 rather than quietly removed.
- **ADR-0200 §3's threading rule is applied to nothing here**, which §7 states with
  its reason. That rule is about a caller waiting on an answer it asked for; this
  ADR's stages sit after a selection the outbox has already leased, and ADR-0135 §3
  is the clause that separates the two. Reading §3's rule across would have been a
  supersession of ADR-0135 by resemblance.
- **ADR-0177 §1 is untouched, and §2 argues it rather than asserting it.** §1's
  thirty-one-operation enumeration gains nothing: `next_notification` is expressly
  "not one of the thirty" and this ADR adds no operation. §1's deadline carve-out
  gains nothing either: `plays` is not a deadline, and the class of arguments the
  gateway supplies of its own already holds `acknowledging` under ADR-0175 §5,
  ratified and shipped before ADR-0177 was written.

- **ADR-0204 is consumed and discharged, not touched.** §3 states what its §3's
  second clause requires of an ADR admitting a delivery-side supply, and states it
  in the direction that withholds. No clause of it is read more widely: the stamp is
  still set only at capture (§2), still inherited only by a producer over records of
  this store (§5), and still applied at a supply site rather than anywhere this ADR
  adds one. A reader holding only ADR-0204 stamps the same records and withholds the
  same ones, so **no record is owed on it**.
- **ADR-0205 is read and left where it stands.** §9 cites its subject and its §8's
  second deferral rather than deciding either; §6 keeps `SpokenRendering` and
  `SpokenDeliveryState` distinct and adds no member to `SpokenDelivery`,
  `SpokenDeliveryReport` or `SpokenTurn`. Its own supersessions — ADR-0200 §3, §4
  and §10, and ADR-0074 §9 — are untouched, and its §10 confirms the figure the
  bullet above rests on: ADR-0177 §1's enumeration is **still thirty-one
  operations**, because `record_delivery` lands on `ConversationStore` rather than
  on the promoted surface. **No record is owed on it.**

**ADR-0200 is consumed on every clause this path touches.** Its §1 Protocols and
its `SpokenAudio`, `SpokenAudioFormat` and `Base64Audio` types are used as
declared; §3's format-choice rule and its budget-threading rule are applied at a
second call site on their own stated terms; §4's translation, degradation and
cancellation lines are applied at a second site; §6's byte bound and §8's
retention and authorship rules bind this path whole; §10's "the front end runs no
speech engine" binds unchanged. One of its deferrals is checked and does **not**
fire: §11's spoken confirmation "**Fires** at the first channel with no screen —
milestone 20's idle device", and milestone 20's idle device is a browser with a
screen, so a parked turn still renders its confirmation where §11 leaves it.

**No *amendment* record is owed anywhere.** ADR-0082 §1 owes one "when the later
ADR amends a named clause — and not otherwise", and this ADR amends none: the two
things it changes it *supersedes*, and the record ADR-0131 owes is made in this
change, on ADR-0082 §7's reading that §1's condition is that the superseding ADR
**exists** rather than that it is ratified, and on ADR-0201 §8's consequence that
"a lane whose fence admits both files may make it atomically."

**This ADR marks its rulings** (ADR-0089 §5), so the marked clauses above are the
whole of what it obligates and the prose beside them is read to determine what a
marked clause means.

**Status.** Drafted, reviewed and revised while `Proposed`. The required set is
**adversarial and architecture**: §1 and §6 decide `core/protocols.py` and
`core/types.py` surface, which `CONTRIBUTING.md` → "Stop when the required reviews
are green" puts in the contract-surface case. The status is flipped only once both
return clean on one tree, by the one-line flip ADR-0165 §2 exempts, and nothing
implements against this ADR until it merges (ADR-0015 §5, golden rule 5).

### 12. What the implementing lane owes

**Which of the rows below ride in one lane is ADR-0137's question and not this
ADR's**, on ADR-0143 §9's precedent for leaving a lane-shape call to the
dispatcher. What is decided here is what each must contain if it exists.

> **Normative.** The `next_notification` argument of §1, the two members and the
> `SpokenRendering` enumeration of §6, the `orchestration` rendering behind the
> poll, and the wire client's matching member land in **one** lane, because a
> member changed on a *provided* contract with two implementations cannot change
> in one of them and leave the gate green. That lane carries the
> `PROTOCOL_VERSION` bump.

> **Normative.** The gateway's fixed `plays` (§2), the interval-paced keep-alive
> (§8) and the page's idle-device playback (§8) land in a lane fenced to
> `interfaces/gateway/`, briefed against the merged text of the lane above, under
> `track:web-client`'s concurrency rule (#1226 §3).

> **Normative.** A lane satisfies the rows of this table that fall inside its
> fence and adds none: a deliverable this table does not name is out of that lane
> and is filed as an issue.

| Clause | Deliverable | Test item |
| --- | --- | --- |
| §1 | `plays` on `next_notification`, keyword-only, defaulting to `()` | An argument-order test; a test that an omitted `plays` produces `NOT_REQUESTED`, calls no synthesizer and changes no other behaviour of the poll |
| §1 (no pre-render) | The rendering is produced inside the answering call | A test that no synthesizer is called at `offer`, at disposition or at reconsideration; a test that a redelivery renders afresh |
| §1 (retention) | No audio in the outbox, any store, trail, trace or log | A test asserting the data directory and both log tiers hold no audio after a spoken delivery |
| §2 | The gateway's `plays` names every `SpokenAudioFormat` member, ordered by a constant the lane records a measurement for | A test asserting the poll argument names every member; a test that no browser value reaches it, over a delivery-stream request that carries one; the measurement recorded beside the constant |
| §2 (one format) | A browser that cannot decode the rendering renders and plays nothing | A page test over a rendering in the member that browser does not decode, asserting the notification is rendered, nothing is played, and nothing is reported |
| §3 | The placement decided from the three recorded fields | A test per triple: the placed one renders; the same producer and class at `OPERATIONAL` is `WITHHELD`; an unnamed producer is `WITHHELD` |
| §3 (stamp) | The placement's condition on ADR-0204 §3 stated and kept | A test that the placed producer's proposals carry `supplied_withheld_content` `False`; a test that the delivery path holds no `MemoryStore` and no `ContextProvider` and issues no store query while answering a poll |
| §3 (no inspection) | No content read to decide a placement | A test that a candidate whose `summary` names an unplaced subject still renders where its triple is placed |
| §4 | `summary` handed to `synthesize` byte-for-byte; `detail` never spoken | A test that the value handed to `synthesize` is byte-identical to `summary`, including leading and trailing spaces; a test that a candidate with a `detail` speaks only the summary |
| §5 | A withheld candidate calls no synthesizer and emits no audio | A test that a `WITHHELD` delivery carries `spoken` `None`, that no synthesizer was called, and that no substitute value of any kind is produced |
| §5 (delivery) | A withheld notification is still returned and still acknowledgeable | A test that the poll returns it, that it is acknowledged normally, and that the outbox holds nothing after |
| §6 | The two members, the enumeration, and the validator stating §6's invariant both ways | Tests constructing each admissible shape and rejecting each inadmissible one, `spoken` beside every non-`RENDERED` member included |
| §6 (values) | The four serialized values exactly as §6 fixes them | A test enumerating `SpokenRendering` and asserting each member's value; a round-trip through `wire/codec.py` asserting the value on the wire |
| §6 (degradation) | The four `DEGRADED` cases | Four tests, one per case, each asserting the delivery still travels |
| §6 (no collapse) | A withholding is never a degradation | A test that a `WITHHELD` delivery is not retried into speech on the next poll |
| §6 (translation) | `SpeechError` degrades; every other exception propagates | Two tests, one each direction, over a synthesizer made to fail |
| §6 (ceiling) | The whole projected delivery measured; the rendering dropped | A near-ceiling test: a candidate lawful for `offer` plus a rendering degrades rather than raising |
| §7 | The rendering performed whatever the state of the budget | A test whose entry is selected with the budget already elapsed, asserting the rendering is produced and `RENDERED` returned; a test that a zero budget selects at once and still renders |
| §7 (no budget degradation) | No implementation degrades on an elapsed budget | A test asserting `DEGRADED` is never returned for a placed candidate whose synthesizer succeeded, at any budget |
| §7 (ordering) | A malformed `plays` refused before any outbox effect | A test that such a poll retires nothing, leases nothing and mints nothing, and that no rendering is attempted |
| §6 (cancellation) | A cancellation propagates from a blocked synthesis and never degrades | A test cancelling the poll while `synthesize` is blocked, asserting `CancelledError` propagates after cancellation-safe cleanup, that no delivery is returned, that none is acknowledged, and that the leased entry returns to the outbox on lease expiry |
| §8 (projection) | `streams.notification` gains `spoken` and nothing else | A test enumerating the value's keys for a rendered and for a withheld delivery; a test that `delivery_id`, `spoken_rendering`, confidence, sensitivity and references appear in neither |
| §8 (shape) | `spoken` is `null` or an object of exactly `content` and `media_type` | A test per shape, asserting the member is present in both |
| §8 | The page plays only with a running context and nothing in the air | A test that a delivery arriving during a playback is rendered and not queued; a test that a page with no context renders and does not play |
| §8 (interrupt) | A press interrupts a notification's playback | A test driving the press against a sounding notification |
| §8 (keep-alive) | The gateway's keep-alive paced by `gateway_notification_budget` and not by the poll's return | A test that with a poll outstanding beyond that interval, every open delivery stream still receives a value within it; a test that the value is the one carrying nothing but its own kind, that it is not a delivery and acknowledges nothing, and that a gateway whose polls complete within budget writes no extra value |
| §8 (keep-alive, stalled) | A stream stalled behind a rendering is abandoned and ended when the keep-alive falls due | A test asserting the abandonment, that nothing is queued behind the pending value, and that no other stream's cadence is delayed by it |
| §8 (keep-alive, coincidence) | A delivery returning as the interval elapses writes once, as the delivery | A test over a deterministic clock making the poll's return and the interval's expiry coincide, asserting exactly one value on each open stream, that it is the delivery, that no keep-alive follows it, and that no stream is abandoned |
| §8 (keep-alive, lifetime) | The keep-alive dropped with the last stream and on shutdown, beside the poll | A test that closes the last stream while a poll is outstanding in synthesis, asserting the poll is cancelled, that whatever carries the keep-alive is cancelled or released with it, that nothing of it is left running, and that no value is written on any stream after; the same over `shutdown` |
| §9 | ADR-0175 §5's acknowledgement unchanged | A test that the acknowledgement rides the next poll whatever the page did with the rendering |
| §11 | ADR-0131's record is made in this ADR's own change | `tests/scripts/test_adr_citations_corpus.py`; a reader of ADR-0131 reaches ADR-0206 from its header |

## Consequences

**Easier.** Milestone 20 becomes a small change rather than a new subsystem: one
argument, two members on a value that already crosses the wire, one enumeration,
and a page that already knows how to decode audio and already holds one playback
at a time. The disclosure question is answered by a table of three fields rather
than by anything that reads a sentence, which is what makes it auditable — a
reviewer can check §3's placement against `orchestration/upcoming.py` in a minute.
And ADR-0199's fourth clause is discharged in the shape it asked for, so the next
producer to land inherits a stated default rather than a habit.

**Harder, and stated plainly.** Every notification producer that lands from now on
is silent by default and stays silent until an ADR places it, which is a tax
ADR-0199 §3 already imposed and this ADR makes concrete rather than theoretical.
A poll that renders answers later than its budget (§7), so a *notification* can
now reach a browser later than one figure used to predict, and the gateway grows a
keep-alive it must pace itself rather than get for free from the poll's return
(§8). That is a real cost and it buys back ADR-0175 §4's cadence exactly; what it
does not buy back is the latency, which §10 defers a measurement for. And a page
that has had no user gesture will not speak at all (§8) — the honest shape of
"proactive speech" on a browser is that the owner has to have spoken to it first,
and no clause here can change a browser's autoplay rule.

The owner also gains nothing here about a class they want *silenced*: ADR-0199
§6's record surface is still deferred, so the only postures available are the ones
§3 writes down. That is a workable steady state and not a good one, and §10 names
the condition that ends it.

**Revisit if** a producer arrives whose sensitivity genuinely varies with its
content, since §3's argument for placing a single tier rests on
`calendar-upcoming`'s being a constant; if a rendering pushes a poll far enough
past its budget for the delay to matter to the owner, which is §10's first
deferral; or if a channel arrives that is
both a delivery target and bounded, since §5 declares this path's rendering
unbounded outright and a bounded one has to arrive as its own declared channel.

## Alternatives considered

**A sibling operation — `next_spoken_notification` — mirroring ADR-0200 §3.** The
symmetry is real and the precedent is one ADR old. Rejected because the ground
ADR-0200 §3 gave does not transfer: there, two operations exist because two
*answers* are composed, one for each channel, and the operation is where the
composing stage learns which. A notification is not composed at all, so both
operations would return the same artifact and differ only in whether audio rode
along — which is what an argument expresses. It would also have put a second
member on the seam ADR-0131 §4 declares, for no capability the argument does not
give.

**Pre-render at disposition and keep the audio in the outbox.** Attractive
because the rendering would then be ready the instant a device asked, which is
exactly the shortfall §7 admits. Rejected outright by ADR-0200 §8, which forbids
audio in an outbox in terms, and independently by cost: the overwhelming majority
of entries are polled by callers that cannot play them, and an entry can be
delivered more than once.

**Let the browser declare the formats it can play.** The technically correct thing
to know, and the shape ADR-0200 §10 already uses for `/ask/spoken`, where `plays`
is a browser-owned argument. Rejected twice: ADR-0177 §1's second clause forbids a
browser argument reaching this poll, and ADR-0175 §4's fan-out gives the gateway
one answer for every open stream, so two browsers with different capabilities
have no single value to be served by. **What replaces it is narrower than the
rejected shape and §2 says so**: naming the whole enumeration keeps the caller
from narrowing what the synthesizer may produce, and one rendering then serves
only the browsers that decode the format the engine picked. A browser that
decodes only the other member is silent, which is the cost of a carrier that
answers once for every reader rather than an argument this alternative would have
bought back.

**Speak a marker where a class was withheld — a chime, or "there is something on
your phone".** The most requested-sounding behaviour, and the one that makes the
milestone's phrase "deflects to an authenticated surface" feel honoured out loud.
Rejected in terms by ADR-0199 §5's silence clause, whose reasoning this ADR has no
answer to: an emission whose entire content is that something was withheld is pure
signal about the existence of withheld content, delivered into a room that did not
ask, with no answer to compensate it. The deflection is that the notification is on
the page, and the page is the authenticated surface.

**Acknowledge when playback ends, so an unheard notification is redelivered.**
The change this ADR most wanted to make. Rejected on ADR-0175 §5's own terms: it
needs either a `delivery_id` in a browser — a minted capability held by a browser,
which ADR-0172 §1 closes its class against — or a gateway holding a token for a
period nothing bounds. Both were weighed and declined when §5 was written, and a
spoken delivery changes neither argument. The cost is a notification spoken over
being one the owner reads rather than hears, which is what the page is for.

**Let the page hold a rendering and play it when the device next goes idle.** The
brief for this lane recommended it and it is the intuitive shape. Rejected because
it is a buffer: unbounded in age, held in a page nothing can inspect, and aging
against an artifact ADR-0130 says is about a moment — "something that keeps is not
an interruption, it is a message". ADR-0175 §4 refused the same buffer one hop in,
for the same reason, and the owner loses nothing by the refusal because the
notification is already on their screen.

**Place every non-secret tier of the calendar producer's class rather than one.**
A one-line change that would make the placement robust to a producer that later
lowered its tier. Rejected because it places a triple no candidate carries,
because ADR-0199 §3's fifth clause is written precisely against a placement
reaching a tier it did not name, and because the withheld half of the milestone's
exit test would then need a producer that does not exist to demonstrate it.

**Rule the whole thing hub-side and leave the browser to a later ADR.** It would
have kept this decision inside `core` and `orchestration` and avoided every
gateway clause. Rejected because milestone 20's exit test is a device speaking in
a room, and a decision that ruled the rendering and not the playing would have
left the two facts that actually decide the behaviour — the audio context, and
what happens to a rendering nobody can play — to be discovered in an
implementation lane rather than ruled here.
