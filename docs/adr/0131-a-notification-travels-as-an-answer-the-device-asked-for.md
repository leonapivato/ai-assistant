# 131. A notification travels as an answer the device asked for, on a connection it keeps for that alone

- Status: Proposed
- Date: 2026-08-10
- **Durability clause.** Every reference below to ADR-NNNN is to its text as it
  stood at this ADR's base, `10e63a12`, not to its status on any later day. Every
  ADR this decision composes with reads `Accepted` there, or is partially
  superseded in a scope this ADR does not touch. Where a later ADR *changes* one
  of them, this ADR is read against the text quoted here and that ADR's own record
  says what moved. The `Date` line is this ADR's authoring date in this clone's
  `-0400` frame, the convention ADR-0112, ADR-0113 and ADR-0129 state for their
  own; the base named here is the anchor that does not move under either frame.

## Context

### A hub that notices and cannot reach the user has delivered nothing

`docs/roadmap.md`'s leg 10 is the propose/dispose principle's last unbuilt
artifact: the hub decides something is worth saying and says it. Leg 9 landed the
half that looks like the answer and is not. ADR-0124 gave the hub an overlay on
which every enrolled device has a routable address, and then spent a marked clause
saying that this is not permission to use it:

> **Normative.** The hub still never dials a spoke. ADR-0094 §2 is unchanged: every
> connection between the hub and a spoke is established by the spoke, and nothing
> in this ADR — including an overlay on which the hub can address the device — is
> permission to initiate one.

and a second one refusing to decide the seam at all:

> **Normative.** No lane may read this ADR as deciding any part of a delivery seam
> for proactivity. That seam is the additive wire decision ADR-0094 §10,
> ADR-0084 §11 and ADR-0042 §5 already defer, and it is unmoved by this one.

ADR-0124 §10 then states the residual in one sentence: "What stands between that
and a delivered notification is not networking; it is ADR-0094 §2's direction rule
and ADR-0084 §3's serial envelope." This ADR is the decision those three deferrals
name. It decides **how a notification travels**, and nothing about what a
notification is.

### The three texts that actually bind, read rather than remembered

**ADR-0094 §2 fixes the direction and says the current protocol cannot carry the
extension.**

> **Normative.** Every connection between the hub and a spoke is established by
> the spoke. The hub may not initiate a connection to a spoke, and a spoke may not
> accept one. Pull is served over a connection the spoke already established.

Its supporting text is unusually explicit about what it left open: "What is
deliberately not decided here is how pull rides the connection, and the current
protocol cannot carry it… So the mechanism is an additive wire decision owing its
own ADR (§10), and this section decides only the direction, which that decision
must not reverse."

**ADR-0084 §3 makes a connection serial, in two rules whose reasons are as
load-bearing as the rules.**

> - **A request frame sent while another is outstanding is a protocol violation,
>   and the connection is closed** — not queued, not run concurrently, and *not*
>   answered with a correlated error.
> - **A response whose correlation id does not match the outstanding request is a
>   protocol violation**, and the connection is closed rather than resynchronised.

`wire/server.py`'s `_serve_requests` enforces the first with a watcher that reads
the next frame *concurrently* with the dispatch, precisely so that a second frame
is refused rather than queued; `_settle` is the function that makes the
observation deterministic. Nothing in the tree tolerates a frame the peer did not
ask for.

**ADR-0124 §1's third accountability bullet is the clause that decides between the
two candidate shapes**, and it is easy to walk past because it reads as a summary:

> **Answerable for what it sends.** The hub sends the response to the request the
> device just made and the client sends the request the owner asked it to make,
> both over the ratified envelope, bounded by ADR-0084 §3's frame ceiling and
> ADR-0085 §8's contract limit. **There is no path by which either transmits
> something nobody asked for.**

That sentence is a *property of the egress boundary* ADR-0017 §1 was widened to
admit. A hub that writes an unsolicited frame at a device makes it false. The
naive push shape therefore does not merely need a wire extension — it needs
ADR-0124 §1's widening re-argued, on the one axis ADR-0017 §4 says egress
accountability is measured by.

### What is genuinely open, and what only looks open

Open: whether the notification rides a frame the device did not ask for, whether
it rides the device's ordinary session connection or one of its own, whether an
undelivered notification survives a hub restart, and what bounds the hub's
holding of one.

Only *looks* open: whether the seam bumps `PROTOCOL_VERSION`. ADR-0124 §9 already
decided that, in terms, and this ADR does not get to weigh it:

> It reaches, without limiting itself to: … and any change to the promoted
> surface's method set or to a method's arguments or results (ADR-0085 §3).

with the prose spelling out the case: "**Adding a method bumps, and that is the
honest consequence rather than an oversight.**" So the only question left is
whether this seam adds a method, and §4 below answers it.

### Two parked questions ride here because this is the decision they were parked for

**#934** asks whether ADR-0124 §7's credential-*type* clause binds the loopback
listener. It was split out of #917's fix (PR #933) and left open because settling
it needs a ruling rather than a patch. It arrives here because this seam
multiplies connections on *both* transports — a notification-taking client is a
second connect frame on loopback as well as across the hop — so "what a connect
frame means on each listener" stops being an abstract question about §7's scope.

**#939** records that the hub trusts its overlay agent socket on a filesystem walk
alone, with no peer authentication after connect, and says why it could not be
fixed in PR #936: "using it means deciding a new normative rule: **which peer uid
may answer as the overlay agent**", and "it is exactly the kind of rule that
belongs in a ratified decision rather than being introduced by an implementation
lane, because it decides who the hub will accept as the source of every admission
identity." It arrives here because this seam makes that identity load-bearing for
longer: a device that keeps a delivery connection open is admitted once, on one
answer from the agent, and then holds a channel the hub writes the owner's
material into.

## Decision

### 1. Delivery is an answer to a request the device made

> **Normative.** A disposed notification reaches a device only as the **result
> payload of a request that device sent**. The hub writes no frame on a connection
> except in answer to an outstanding request, and no lane may add a frame kind, a
> message class or a transport path by which the hub writes to a device
> unsolicited.

> **Normative.** The request that delivery answers is a single method on the
> promoted surface, `next_notification`, and it is the only method by which a
> notification crosses the wire.

The device asks "have you anything for me, and I will wait up to this long"; the
hub answers with a notification the moment it has one, or with nothing when the
device's patience runs out. That is a long poll, and naming it plainly is worth
more than naming it cleverly.

**This is the shape that costs no clause anywhere, and the alternative costs
three.** Take them in order.

- **ADR-0094 §2** is satisfied without argument: the device establishes the
  connection and the hub answers on it. §2's own sentence — "Pull is served over a
  connection the spoke already established" — describes this exactly, in the
  direction §2 was written for.
- **ADR-0084 §3** is satisfied without extension. A poll is one request frame and
  one result frame, correlated, one at a time. The serial rule is not bent, the
  correlation id keeps the single job §3 gave it, and §3's read deadline already
  exempts a slow dispatch — "the idle deadline applies where the hub genuinely is
  idle — waiting for the *first* frame of the next request." What §2a below does
  require of the server is a way to notice the *connection* going away while a poll
  is outstanding, which the existing path does not have; an earlier draft claimed
  `_serve_requests` needed no new branch at all, and that claim was wrong.
- **ADR-0124 §1** stays true word for word. The hub sends "the response to the
  request the device just made". There is still no path by which it transmits
  something nobody asked for.

**Server push is the shape that reads as obvious and is the expensive one, and the
expense is not the code.** A `notify` frame the hub writes when it feels like it
requires: a new frame kind, so a client must demultiplex an unsolicited frame from
a correlated response, which is the multiplexing ADR-0084 §3 deferred rather than
a use of the id it kept; a rule about what happens when such a frame arrives while
a request is outstanding, which is the one input §3 says has exactly one answer
today; and ADR-0124 §1's accountability bullet re-argued, because the hub would
then transmit something nobody asked for. Two of those three are contract changes
to ratified text. The long poll needs none of them, and it needs none of them not
by cleverness but because the corpus's serial request/response was already an
adequate carrier for "tell me when" — the thing it could not carry was "I will
tell you", which is the direction §2 forbids anyway.

**What the seam carries is a disposed notification, and this ADR does not know
what one is.** ADR-0130 decides the artifact, who may produce one, and what earns
an interruption. This ADR requires only that the delivered value be a promoted
`core` model, because ADR-0084 §3 requires it of every result payload — "a
**result** payload is a promoted `core` model (§4)" — and §4 below fixes the one
member the *seam* needs around it.

### 2. A device that takes notifications keeps a connection for that alone

> **Normative.** A `next_notification` request is sent on a connection carrying no
> other request for its lifetime. A client that has a poll outstanding sends no
> other request on that connection, and a client wanting an ordinary session while
> polling opens a second connection for it.

**This falls out of ADR-0084 §3 rather than being chosen against it**, and stating
it as a rule is what stops the first implementation from discovering it in
production. The serial rule means one outstanding request per connection. A poll
that waits ninety seconds for something to happen is an outstanding request for
ninety seconds. Share the connection and every `converse` the owner types is a
protocol violation that closes the connection — §3 is explicit that a second
request while one is outstanding is "not queued, not run concurrently", and
`_serve_requests` implements exactly that. So a shared connection does not degrade
under load; it is simply broken, on the first turn the owner takes while a poll is
in flight.

**Two connections is cheap here in a way it would not be elsewhere**, and the
reason is ADR-0084 §7's: "the client is stateless (§7) — so reconnecting costs it
nothing". A delivery connection holds no session, no continuation, no cursor. Its
whole state is "a poll is outstanding", and §3 below puts the state that matters
in the hub where a restart cannot lose it.

> **Normative.** A device holds at most one delivery connection. A second
> `next_notification` request from a device that already has one outstanding causes
> the hub to close **the connection that made the second request**. The connection
> that was already polling is untouched, and neither is answered.

> **Normative.** The slot's check and claim are **one step**, taken before the
> request is dispatched. Among requests racing for one device's slot exactly one
> claimant wins and every loser closes its own connection; the winner holds the slot
> until it is released under §2a.

**"Already has one outstanding" is a read, so the claim that depends on it has to be
the same step.** Two delivery connections opened at once can otherwise both observe
no outstanding slot before either records one: both dispatch, the device holds two,
neither is the second, and §2's rule fails without any implementation disobeying a
word of it. Adversarial review found it on the twenty-second round, and §3's
linearizability clause is stated over the seam's shared state — the slot registry
included — for exactly this reason. Taking the claim *before* dispatch is what makes
"exactly one wins" decidable: after dispatch the losing poll would already be
running and the rule would have to unwind it. §5's global capacity is claimed in the
same step, for the reason given there.

**Closing the offender and not the incumbent is the direction that cannot be used
as a weapon.** The opposite rule — newest poll wins — lets any process that can
reach the listener evict the owner's real notifier by polling, and the eviction
would look to the notifier exactly like an ordinary transport failure. Closing the
second connection costs its caller nothing it can complain about: the client is
stateless (ADR-0084 §7), so reconnecting is free, and the entry it was after is
still in the outbox.

**A typed error here would be the wrong instrument, and ADR-0084 §3 says so
directly.** An earlier draft made it a correlated error on the reasoning that both
frames decoded and the second broke no framing rule. That reasoning stops one
clause short. §3's second bullet reads: "**A frame that decodes gets a typed error
rather than a silent close — provided it is not itself a violation of the
connection's own rules.**" A second poll is exactly such a violation — the same
class as the serial rule, and answered the same way. Architecture review found the
consequence of getting it wrong: a typed error would have to be declared on
`next_notification`, and it could only ever be raised by the *transport*, since the
fact it turns on is the connection-scoped identity §4 keeps out of the engine. That
breaks the substitutability ADR-0084 §5 promoted the façade to a Protocol for — an
in-process engine has no connections and could never raise it, so the same declared
contract would mean two different things depending on which side of the wire the
caller stood.

### 2a. A poll whose connection has gone releases the slot it held

> **Normative.** While a `next_notification` request is outstanding, the hub
> detects its connection closing. On detecting it the poll ends without an answer
> and the device's delivery slot is released.

> **Normative.** Selecting an entry, minting its `delivery_id` and starting its
> lease are **one indivisible step** inside `next_notification`. There is no state
> in which an entry is chosen for a poll and not yet leased, and nothing about the
> lease depends on the transport.

> **Normative.** A close detected before that step runs cancels the poll and takes
> no entry. A close detected after it leaves the lease standing, and the entry
> returns to the outbox when the lease expires under §3.

> **Normative.** A poll arriving from a device whose previous poll has ended but
> whose slot has not yet been released is closed under §2, and the device may
> reconnect. No lane may resolve that race by evicting a live poll.

**The existing server path does not detect the close, and saying so is the point of
the first clause.** `_serve_requests` (`wire/server.py`) reads the next frame
concurrently with the dispatch — which is how it catches an overlapping request —
but it settles that watcher only *after* `_dispatch` returns. For every request the
hub has ever served that ordering is correct and invisible, because the dispatch is
short. A long poll is the first request for which it is not: the watcher observes
the peer's clean close within milliseconds and nothing acts on it until the poll's
budget has run out, so the device's slot stays held by a poll nobody is listening
to, and the reconnect §2 calls free is closed as a second poll — the claim and the
rule contradicting each other on the most ordinary failure a mobile device has.
Adversarial review found it on the eleventh round, and this is the one place the
seam genuinely reaches into the server's request loop.

**The lease begins inside the engine call and not at the write, and getting that
backwards cost four rounds.** A draft made the lease commit at the result frame's
write, on the appealing reasoning that the write is where the hub commits to a
device having been told. It is not implementable behind this Protocol.
`_serve_requests` awaits `_dispatch`, builds the result envelope from the
`NotificationDelivery` the engine returned, settles the overlap watcher, rechecks
revocation and only *then* calls `write_frame` — so the identifier and everything
in the result exist before the write is known to happen. Honouring a write-time
commit would take a prepare/commit/abort boundary the promoted surface does not
have, and an in-process caller has no write at all, so the same `AssistantEngine`
would mean two different things on the two sides of the wire — the substitutability
ADR-0084 §5 promoted the façade for. Adversarial review found it on the
seventeenth round.

**What that costs is one lease, and it is the cost the lease exists to carry.** An
entry selected just as the connection dies is leased to a device that never receives
it, and comes back when the lease expires rather than immediately. That is precisely
the at-least-once case §3 already describes — a device that receives a notification
and dies before acknowledging — reached one step earlier, and `hub_notification_lease`
is the figure that bounds it. The clause the earlier draft was reaching for is worth
having and this one keeps it: the *slot* is released on the close, which was the
eleventh round's actual complaint.

**Indivisible selection is what a two-transition split was doing badly.** An earlier
draft separated a *reservation* from the lease, so that a closed poll could leave
nothing behind. It bought one property and owed three clauses for it: the twelfth
round asked what ordered a close against the commit, the thirteenth found that
eviction could drop a reserved entry and that a persisted reservation survived a
restart with no rule releasing it, and the fourteenth found that classifying an entry
and dropping it could straddle the commit. Every one of those was a consequence of
the split rather than of the problem. Collapsing it removes all four questions at
once: with selection and leasing indivisible, an entry is available or leased and
there is no third state for eviction, a restart or a race to have an opinion about.

**The residual race is stated rather than engineered away.** Close detection is
asynchronous, so a device fast enough to reconnect inside it meets a slot that is
about to be free. Closing and letting it retry is correct and costs a stateless
client one reconnect; the alternative — letting a new poll displace the incumbent —
reintroduces exactly the eviction §2 exists to prevent, and would do it for a
condition an attacker can manufacture at will.

### 3. The outbox: one queue for the owner, durable, bounded, leased, at-least-once

> **Normative.** A disposed notification is placed in a durable **outbox** in the
> hub's data directory before it is offered to any device, and it survives a hub
> restart. A notification the hub has disposed and not yet delivered is never held
> only in memory.

> **Normative.** The enqueue is a **single durable commit**, and the seam reports
> its outcome to the caller that offered the notification. The seam takes custody
> at that commit and not before, so a caller that has not seen the enqueue succeed
> has not handed the notification over.

**The second clause is where the discipline below actually bites, and stating the
first alone would have claimed it without applying it.** ADR-0094 §10a's first
custody clause forbids "an acknowledgement precede the hub's durable custody of the
submitted material" — the same failure, mirrored: a producer that treats a
notification as disposed, and the hub that crashes between that act and a separate
outbox write, together lose a notification that every clause here says survives a
restart. Making the enqueue the single commit *and* the point custody transfers is
what closes the window, and reporting its outcome is what leaves the producer able
to do something about a failure. **What the producer then does is ADR-0130's** —
retry, drop, record — and this ADR neither decides it nor needs to; the seam's
obligation is to have an unambiguous answer for the producer to act on.

> **Normative.** The enqueue accepts an optional caller-supplied **origin key**, an
> `Identifier` whose UTF-8 encoding is at most 128 bytes; a longer one is refused at
> the enqueue. An enqueue whose origin key equals that of an entry the outbox
> currently holds, **and whose offered notification is identical to that entry's**,
> makes no new entry and returns the held one. Retired keys are not remembered, and
> an entry carrying no origin key is never matched against anything.

> **Normative.** An enqueue whose origin key matches a held entry's while the
> offered notification differs from it is **refused** as a key collision, with an
> outcome distinct from a successful match. The held entry is not replaced and the
> offered notification is not enqueued under another key.

**Matching on the key alone would turn a producer's bug into a silent loss**, which
is the third round's finding and the exact failure mode the key was added to
prevent, arriving from the other side: a producer with a low-cardinality or simply
mistaken key enqueues B under the key A already holds, receives what looks like a
successful enqueue, and B is never told. Comparing the notification is what makes
the no-op a *retry* rather than a coincidence, and refusing the collision is what
makes the difference reach the producer instead of the floor. Equality is
well-defined without this ADR inventing anything: ADR-0087 §2 gives every payload a
canonical encoding, and two notifications are identical when theirs are.

**A commit the caller never learns the outcome of is the case this exists for, and
it is a narrower case than it first looks.** The hub can commit the entry and then
die before the call returns; the producer, restarting, may offer the same
notification again. The origin key makes that retry a no-op rather than a second
telling — the reviewer's finding on the second round, and correct.

**Two things are deliberately *not* bought, and pretending otherwise would be the
larger error.** First, **a producer with no durable identity for its own
notifications gets no protection**, because it has no key to send. Whether
ADR-0130's producer has such an identity — and whether its noticer re-notices after
a restart at all — is ADR-0130's question and #632's durable cursor is adjacent to
it; the seam supplies the slot and cannot supply the identity. Second, **retired
keys are forgotten**, so a retry arriving after the notification has been delivered
and acknowledged makes a second entry. Remembering them would mean a durable set of
every key the hub has ever seen, growing forever, bounded by nothing — a worse
failure than the one it prevents, traded for a window that only opens when a crash
lands between a commit and a return *and* the delivery has already completed. The
bound is where this ADR spends its durable state, and it spends it on entries.

**Silence on this is the one thing the corpus forbids outright.** ADR-0094 §10a
binds the mirror-image decision — the spoke-to-hub custody handoff — with "An ADR
deciding the custody handoff states explicitly whether an unresolved submission
survives a spoke restart… It may not settle that question by silence." Those
clauses do not bind this ADR, because their subject is *submitted material*
travelling the other way (§9 records the classification). The discipline is
adopted anyway, and the answer is durable, for a reason particular to this
deployment: ADR-0124 §11 records that "a laptop hub sleeps", and a hub that
notices something at 02:00, restarts at 03:00 and has forgotten it by morning has
produced exactly the failure this leg exists to close, in the deployment the
roadmap says we actually have.

> **Normative.** The outbox is the owner's, not a device's. An entry is offered to
> **one** device at a time — the first to ask for it — and is retired when that
> device acknowledges it. No entry is ever outstanding to two devices at once.

**Retirement is on the acknowledgement and not on the write, and an earlier draft
said both.** It said an entry was retired by being delivered *and* that a written
entry stayed leased until acknowledged or expired, which cannot both hold for a
device that receives a result and dies before acknowledging: the entry is retired
and awaiting redelivery at once. Adversarial review found it on the second round.
The lease clauses below are the ones that were right — retirement is the terminal
transition and the write is not — so the routing rule is stated in terms of what
is *outstanding*, which is the property "one telling" actually needs.

**One notification, one telling.** ADR-0099 §1's single principal is one person,
and a reminder that arrives on the laptop and the phone and the second laptop is
three interruptions bought with one decision — which is the thing ADR-0130's
policy exists to ration, undone by the transport underneath it. First-to-ask is
crude and it is *knowingly* crude: the question it declines is "which device is
the owner actually at", which is a context question about a device, and ADR-0124
§10 already defers a device as a context facet and a device-scoped permission
input (#920). §8 records the deferral rather than leaving the crudeness to be read
as a considered view of where people are.

> **Normative.** A delivery is **leased**. An outbox entry taken for a poll is
> unavailable to any other poll until the device acknowledges it or the lease
> expires, and on expiry it returns to the outbox and may be delivered again.

> **Normative.** The lease runs for `hub_notification_lease` (§5a). It starts in the
> indivisible step §2a fixes, measured on the hub's clock, and no value a device
> sends influences it.

> **Normative.** A hub restart voids every lease. An entry leased when the hub
> stopped is available again when it starts, and no lease survives the process that
> granted it.

**A lease with no stated duration is not a lease** — it is the indefinite hold the
clause was written to prevent, and the finite-terminal-outcome property below would
be an assertion rather than a consequence. §5a carries the figure, because
ADR-0093 §5 forbids naming a bound here and settling it elsewhere.

**The hub's clock, and no device's.** A device that could choose its own lease
could hold an entry for as long as it liked, which hands the eviction rule below to
whichever peer asks for the longest lease. This is ADR-0094 §5's shape applied to a
different quantity — the hub decides, a submission never raises its own — and the
reason is the same one: a bound a peer sets is not a bound.

**Voiding leases on restart is the only answer that is both correct and free.** A
lease is only meaningful while the connection that took the delivery exists, and no
connection survives a hub restart — so an entry still leased at startup is one whose
holder is definitionally gone. Carrying leases across a restart would mean a hub
that came back in ten seconds waited out a full lease before anyone could have the
entry, which is latency bought for nothing.

> **Normative.** A device acknowledges a delivery by naming its `delivery_id` on
> its **next** `next_notification` request. The acknowledgement retires the entry
> **only where that `delivery_id` is the entry's current outstanding delivery**. An
> acknowledgement naming anything else — an unknown identifier, a retired entry, or
> a delivery the entry has since superseded — is accepted and does nothing.

> **Normative.** The seam's **shared state** is *every* piece of state this seam
> keeps that more than one request, poll or producer can observe or change. It is
> defined by that property and not by a list.

> **Normative.** **Every** transition of that state is linearizable with respect to
> every other: each observes the state some serial order of them would produce, and
> none may act on an observation another has since invalidated. Where a transition
> must read two parts of the shared state and act on both, the reads and the act are
> one step over both.

> **Normative.** Seven transitions are named here **as illustration and not as a
> bound** — an enqueue's origin-key decision, bound check, eviction and insertion
> (§3); a selection with its mint and lease (§2a); an acknowledgement's match and
> retirement (§3); a lease expiry (§3); an eviction's classification and drop (§3); a
> delivery slot's check-and-claim and its release (§2, §2a); and the global
> delivery-capacity check, claim and release (§5). Anything meeting the definition
> above is inside the rule whether or not it appears here.

**One rule over the whole class, because closing these pairwise closed none of
them.** Adversarial review found the same shape four times against four different
pairs: eviction against the reservation-to-lease commit on the fourteenth round,
eviction against the collapsed selection-and-lease step on the eighteenth, an
acknowledgement against a redelivery on the twentieth, and the enqueue against
itself and everything else on the twenty-first. The twentieth's case runs: device
A's lease on delivery `D` expires while A is reconnecting to acknowledge it; an
implementation reads that `D` is current, device B's selection then mints delivery
`E` for the same entry, and A's retirement lands on its stale read. B holds `E` and
the entry is gone, so acknowledging `E` is a no-op and no redelivery is possible — a
notification delivered to a device that will never have it confirmed and never have
it again. Four findings, one defect: a predicate stated over outbox state binds
nothing unless the read and the act that depends on it are one step.

**Twice now the rule has been narrowed by the way it was written rather than by what
it meant, and both narrowings are worth recording because they are the same
mistake.** The twenty-first round found a draft that generalised from pairs to a
*set* and then wrote the set as a closed enumeration of four, omitting the enqueue —
the transition that mutates most. Two producers can then each observe room below a
256-entry bound and each commit, leaving 257; two concurrent enqueues carrying one
origin key can each observe no held entry and both insert, so the deduplication §3
spends a clause on and the collision refusal beside it both silently fail. The
twenty-second round then found the *subject* narrowed the same way: stated over "the
outbox", the rule said nothing about the per-device slot registry, so a device
opening two delivery connections at once can have both handlers observe no
outstanding slot before either records one, and §2's one-connection rule fails with
neither connection closed as the second. So the subject is the seam's shared state
and the list is explicitly illustrative. **The lesson is that a rule against stale
reads must not itself be scoped by an enumeration**, of either its members or its
subject — that is exactly how it acquires the gap it was written to remove.

**This is ADR-0124 §8's instrument taken to its general form.** That section
required a liveness check and the write it authorises to be "one step with respect
to a revocation", and could state it pairwise because it had two transitions. How an
implementation discharges the general form — holding transitions against one
another, or re-reading immediately before acting and falling through to the rule the
fresh state implies — is its business; what is not is acting on a reading something
else has invalidated.

**Piggybacking the acknowledgement is what makes the outbox one-deep per device
rather than a second protocol.** The device that has shown a notification wants
the next one; asking for the next one is therefore the natural moment to say it
got the last one, and folding the two into one call means the seam needs one
method rather than two and no state machine on the client beyond "the id I am
holding". The idempotent no-op on anything else is what lets a client reconnect
after any failure and acknowledge blindly rather than having to reason about what
the hub remembers.

**The "current outstanding delivery" condition is what stops a stale holder
retiring someone else's notification**, and it is the sixteenth round's finding.
Device A takes a delivery and goes quiet; the lease expires; the entry is delivered
to device B. An acknowledgement scoped to the *entry* would let A — reconnecting an
hour later and acknowledging what it still holds — retire B's delivery, possibly
before B has shown it, losing the notification and falsifying the at-least-once
guarantee stated two paragraphs down. §4 makes each write mint a fresh
`delivery_id` precisely so that this condition is decidable without the hub knowing
who is asking: A's identifier is simply no longer the current one, and its
acknowledgement lands on the no-op arm that every other stale acknowledgement lands
on.

**The lease is what gives every entry a terminal outcome in finite time**, which
is the property ADR-0094 §10a demands of the mirror decision and which a
hub-side queue loses the instant one dead client can pin an entry forever. It also
fixes the delivery semantics honestly: this is **at-least-once**. A device that
receives a notification, shows it, and dies before acknowledging will be shown it
again. That is the right side to fail on for a notification — a repeated reminder
is a small annoyance and a lost one is the whole failure — and it is stated rather
than discovered. The bound below names the one place that guarantee is
deliberately given up, and gives the reason there.

> **Normative.** The outbox is bounded per hub by `hub_notification_outbox_entries`
> and `hub_notification_outbox_bytes` (§5a). Both bounds count **every** entry the
> outbox holds, leased or not.

> **Normative.** An entry's byte cost is everything the outbox persists for it —
> the notification, the origin key where one was supplied, and the identifier of its
> current outstanding delivery where it has one.

> **Normative.** When an enqueue would exceed either bound, the hub drops entries
> **until both bounds hold with the new entry counted** — each drop taking the
> oldest entry that is not leased, or, when every remaining entry is leased, the
> oldest entry, breaking its lease. Every drop is recorded in the hub's log naming
> the entry, and the enqueue then proceeds.

> **Normative.** An entry whose own byte cost exceeds `hub_notification_outbox_bytes`
> is refused at the enqueue, and the refusal is the enqueue's reported outcome. It is
> never satisfied by evicting other entries.

**An unbounded queue behind an offline owner is a disk-filling bug with a product
name.** Dropping the oldest rather than refusing the newest is the choice a
notification's own nature makes: an outbox that is full is one whose owner has not
been reachable, and of the notifications waiting, the stale ones are the ones worth
least. The drop is logged because a silent drop is indistinguishable from a
producer that never fired, and #939's own standard applies — a gap named is a gap
someone can close.

**The eviction rule is stated as a total function because the interesting case is
the one a partial rule leaves undefined.** "Drop the oldest undelivered entry" has
no subject when every entry is leased, and an implementation reaching that state has
two illegal moves available — retain the new entry over the bound, or drop a leased
one against the rule — with nothing to choose between them. So the leased case is
named: leases are preferred *last*, and the tie-break is the same age order.

**Two classes and not three, and §2a is why the third one is gone.** Drafts between
the twelfth and sixteenth rounds carried a *reservation* — an entry chosen for a
poll but not yet leased — and eviction then needed a third class, an ordering
against the reservation-to-lease commit, and a restart rule of its own, each found
by a separate round. §2a now makes selecting an entry and leasing it one indivisible
step, so no such state exists: an entry is available or it is leased, and eviction
has exactly two classes to order.

**Eviction's own stale-read case is one of the three the linearizability clause
above was written from, and it is worth seeing concretely.** Eviction observes the
oldest entry as unleased, a concurrent poll leases it and returns the delivery, and
eviction removes it on its stale reading — leaving a device holding a delivery whose
record is gone, so its acknowledgement is a no-op and no redelivery is possible.
Note what makes that a defect rather than an instance of the leased rule: dropping a
leased entry is *sanctioned* here and forfeits only the redelivery, but on the stale
path the rule never knew the entry was leased, so the forfeit is reached without the
decision that authorises it.

**It drops until the bounds hold, not once, and the difference is not pedantry.**
One drop is enough for the count bound, where every entry costs exactly one — but
not for the byte bound, where entries differ in size by orders of magnitude. An
outbox one byte below a 1 MiB bound whose oldest entry costs a byte, taking a
512 KiB entry, is half a megabyte over after the single drop the earlier draft
authorised, and the clause then said "the enqueue proceeds". Adversarial review
exhibited exactly that arithmetic on the seventh round. The loop terminates because
each pass removes an entry and the incoming entry is separately guaranteed to fit
by the refusal clause below — so in the worst case the outbox empties and holds one.

**The refusal clause is what keeps the eviction rule from emptying the outbox for a
single entry that could never fit**, and §4's delivery reserve is what makes it
unreachable in a conforming deployment rather than merely rare. Take the arithmetic
end to end, because an earlier draft did it wrong by one step. ADR-0085 §8's
contract limit is `hub_max_frame_bytes` less §8b's 512-byte envelope reserve, and
what is measured against it is the **result**, which here is a
`NotificationDelivery` and not the notification inside it. §4 therefore bounds the
nested notification at the contract limit less a 256-byte delivery reserve. An
entry's byte cost is then that notification, plus a `delivery_id` of at most 96
bytes, plus an origin key of at most 128 — so at most `hub_max_frame_bytes` less
512, less 256, plus 224: comfortably below §5a's floor of `hub_max_frame_bytes`. An
outbox at the floor therefore holds any notification the wire can carry, and the
clause exists for the deployment that is not conforming rather than for the one
that is.

**Breaking a lease is the cheapest thing available to break, and saying what it
costs is the point of ruling it rather than leaving it.** A leased entry has already
been written to a device, so in the ordinary case it is on a screen; dropping it
forfeits the *redelivery*, not the notification. That degrades at-least-once to
at-most-once for that one entry — the only place in this ADR where it does — and it
buys the bound a total rule. The state is also transient by construction: leases
expire, so an outbox in which every entry is leased is one the passage of time
empties without anything else being done.

> **Normative.** The outbox holds notifications and nothing else. It is not a
> memory, not an episode and not a trace; no lane may route it through
> `MemoryStore` or `TraceStore`, and nothing in it is a record any retrieval path
> reads.

### 4. The surface this seam needs, and the `PROTOCOL_VERSION` bump that follows

ADR-0124 §10 forbids *that* ADR from deciding `core` surface and says what a lane
that needs it must do: "An implementing lane that finds it needs either stops and
owes its own contract ADR, merged first (golden rule 5, ADR-0015 §5)." This ADR
is that contract ADR for the delivery method. It decides the method, the one model
and the one error type the *seam* needs; it decides nothing about the notification
inside it.

> **Normative.** `AssistantEngine` (`core/protocols.py`) gains exactly one method
> for this seam:
>
> `async def next_notification(self, *, acknowledging: Identifier | None = None, budget: timedelta) -> NotificationDelivery | None: ...`

Both arguments are keyword-only, which is ADR-0085 §2's convention applied rather
than chosen: "The subject of a call — the one thing it acts on — is positional.
Every other argument is keyword-only." A poll has no subject; both arguments are
modifiers, in the shape `observe(*, conversation_id=…)` and `questions(*, limit,
offset)` already have.

> **Normative.** `core/types.py` gains one frozen pydantic model for this seam,
> declared exactly as below, where `DisposedNotification` stands for the type
> ADR-0130 promotes for a disposed notification and is the only part of this
> declaration ADR-0130 supplies:
>
> `class NotificationDelivery(BaseModel):`
> `    model_config = ConfigDict(extra="forbid", frozen=True)`
> `    delivery_id: Identifier`
> `    notification: DisposedNotification`

**`extra="forbid"` is load-bearing here and is not the house default**, which is
why it is spelled out rather than left to the reader: `core/types.py` carries both
shapes, twenty-two models frozen alone and some fifty forbidding extras as well.
This one must forbid, because the reserve above is otherwise defeated by the
measuring order the tree actually implements. `wire/client.py` validates and *then*
measures — `return_adapter(method).validate_python(reply.payload)` followed by
`check_payload(result, …)` — which is ADR-0087 §7's ordering applied correctly, and
under pydantic's default an unknown member is dropped by the validation. So a peer
could send a conforming delivery plus a large unknown member: under the frame
ceiling, over the contract limit, and measured after the member it smuggled has
already been discarded. Forbidding extras makes the frame refuse at validation
instead. Adversarial review found it on the fifth round, with the mechanism read off
the tree rather than assumed.

> **Normative.** `delivery_id` is minted **once per delivery**, in the indivisible
> step §2a fixes, and is the value `acknowledging` names. A redelivery of the same
> entry carries a new one, and minting it makes the previous one no longer that
> entry's current outstanding delivery (§3). It is a **strictly increasing counter
> held durably with the outbox**, rendered as a decimal string, joined by `.` to a
> **128-bit value from a cryptographically secure source**, rendered as lowercase
> hex. Its UTF-8 encoding is at most 96 bytes.

> **Normative.** A `delivery_id` is unique over the outbox's whole life and is never
> reused, for any entry. The counter advances once per delivery and never goes
> backwards, a restart included.

> **Normative.** A delivery that would advance the counter beyond what the
> identifier's 96-byte bound leaves room to render does not happen: the poll answers
> as though the outbox held nothing for it, and the condition is recorded in the
> hub's log. The counter is never wrapped, reset or reused to make room.

**Per delivery and not per entry, and the entry-scoped version was the defect.** An
earlier draft made the identifier "stable across redeliveries", reasoning that a
device holding it across a reconnect could then acknowledge what it had received.
That reasoning is right only while the entry has not moved on. Once a lease expires
and the entry goes to a *second* device, a stable identifier lets the first device
retire the second's delivery — possibly before it has been shown — which loses the
notification and falsifies §3's at-least-once guarantee. Adversarial review found it
on the sixteenth round. Minting per delivery keeps everything stability was for: a
device reconnecting before any redelivery still holds the current identifier and its
acknowledgement still lands, and one arriving after a redelivery holds a superseded
one and lands on the no-op arm.

**"Per delivery" is not "at the write", and the seventeenth round is why that
distinction is spelled out.** A draft said the identifier was minted at the result
frame's write, which cannot be honoured behind this Protocol: `_serve_requests`
builds the result envelope from what the engine returned and writes afterwards, so
the identifier necessarily exists before the write, and an in-process caller has no
write at all. §2a puts the mint in the same indivisible step as the selection and
the lease, which is inside the engine call on both sides of the wire. A delivery that
is minted and then never reaches its device is exactly the at-least-once case the
lease carries, and it costs one identifier out of `10^63`.

**Uniqueness has to be a clause because `Identifier` does not supply it**, and the
gap is reachable rather than theoretical: the alias rejects only blank text, so a
conforming minting implementation could issue the same value twice, or reuse one
after a retirement. An acknowledgement then retires an entry the caller never
received. Adversarial review found it on the sixth round.

**Two halves, because the identifier carries two obligations and neither half
carries both.** The corpus reached this in two steps and both are worth recording,
because the shape looks like belt-and-braces until you see what each part answers.

**The counter is for uniqueness.** An earlier draft said "a UUID is unique by
construction", which is false: a v4 UUID is collision-*resistant*, and the clause
above asks for a guarantee rather than a probability. Adversarial review was right
about that on the seventh round, and its directed fix — retain a durable history of
every identifier ever minted — was the wrong instrument, being precisely the
unbounded durable set §3 refuses for origin keys. A monotonic counter gives the
guarantee *constructively* for one integer of durable state the outbox is already
paying a durable store to hold. No collision to retry, no history to keep.

**The random half is for unguessability, and it is there because the counter alone
created a capability anyone could forge.** With a bare decimal identifier, a device
that has seen `41` can send `acknowledging="42"` and retire an entry leased to
*another* device that has not yet shown it — losing a notification outright and
falsifying §3's at-least-once guarantee. Adversarial review found it on the twelfth
round, and it is a defect the seventh round's own fix introduced: making the
identifier predictable is exactly what a UUID was accidentally preventing. So the
identifier is treated as what §3 now says it is — a capability — and 128 bits from a
secure source is what makes holding it mean something.

**The alternative was to bind an acknowledgement to the lease-holding device, and it
is not available here.** That needs the connection-scoped identity §4 keeps out of
the engine, for the substitutability reason architecture review established on the
ninth round. A capability needs no identity at all: the entry was written to exactly
one device, so exactly one device holds the token, and the engine can honour it
without ever knowing who is asking. It is the same move ADR-0124 §6 makes with an
enrolment credential — a secret disclosed once to one holder, checked without a
directory.

**Exhaustion is unreachable and is ruled anyway, which is this ADR's own standard
applied to its own clause.** Two bounds meet at the identifier — 96 bytes, and a
counter that may only increase — so a counter that has consumed every digit the
bound leaves beside the separator and the 32-character token is a state the pair
genuinely defines, and an earlier draft gave it no conforming outcome: reuse is
forbidden, a 97th byte is forbidden, and proceeding was not authorised. That is
exactly the partial-rule defect §3's eviction clause was rewritten twice to remove,
and adversarial review found this one on the eighth round. Declining the write is
the answer; wrapping or resetting is not, because both break the uniqueness the
counter exists to supply. The figure will not be reached — 63 digits is `10^63`
writes, which at a delivery a second is some `10^55` years — and a rule that is
never exercised is still cheaper than a state with no defined outcome.

**Where the guarantee stops, named rather than left to be discovered.** It is a
property of one data directory's life. Restoring an older copy of the directory
rolls the counter and the entries back together, so a device still holding an
identifier minted after that copy was taken could name an entry that no longer means
what it meant. The harm is bounded to one entry and the acknowledgement is
idempotent, and the general question — what a restore does to state a peer is
holding — is ADR-0123's and is not reopened here.

> **Normative.** `DisposedNotification`'s canonical encoding is bounded by ADR-0085
> §8's contract limit **less a 256-byte delivery reserve**. ADR-0130 states that
> bound as a constraint on its own type; a notification exceeding it never reaches
> the outbox.

**The reserve exists because what ADR-0085 §8 measures is the result, and the
result is the wrapper.** A `DisposedNotification` sized at exactly the contract
limit is a notification the hub could accept and could never deliver: wrapping it as
`{"delivery_id":…,"notification":…}` puts the *result* over the limit, so the hub
must either refuse what it took or write a frame the client is obliged to reject.
§8b's 512-byte reserve does not cover this — it is reserved for the **envelope**,
outside the payload, and the members added here are inside it. Adversarial review
found the gap on the fourth round.

**256 bytes is a reserve rather than an exact figure, in §8b's own shape and for
its own reason.** The exact overhead is 130 bytes at most: 34 structural — the
braces, the two quoted member names `"delivery_id"` and `"notification"`, the two
colons and the comma, in ADR-0087 §2's canonical form — plus at most 96 for the
identifier. Reserving 256 covers that with margin, and the margin is what stops a
later member on this model from being a silent overflow instead of a recomputation.
It was 128 until the twelfth round widened the identifier from 36 bytes to 96 to
carry a capability; recomputing rather than rounding is what the margin exists to
make survivable, and this is it being used.

**Stating the bound here and having ADR-0130 carry it is the division the two lanes
already have.** The carrying capacity is the seam's fact — it falls out of
ADR-0085 §8 and this model's shape, neither of which ADR-0130 decides — and the
type it constrains is ADR-0130's. So this ADR computes it and ADR-0130 states it on
the type, in the same relationship as the prerequisite clause above.

**Naming the fields is not fussiness at this altitude, it is the whole reason a
surface ADR exists.** ADR-0085 §3 spells out every signature rather than
abbreviating because "this block is what an implementation is generated from", and
§4 gives twenty-four promoted types "and their normative fields" for the same
reason. A clause saying the model "carries an identifier and a notification" leaves
one implementation free to emit `{"id": …}` and another to require
`{"entry_id": …}`, both conforming and mutually unintelligible — which is exactly
the interoperability failure ADR-0084 §3 made framing and codec normative to
prevent, arriving one layer up. Adversarial review found it on the third round.

> **Normative.** ADR-0130 is a **prerequisite of the implementing lane**, not
> merely context for it. `NotificationDelivery` has no complete field layout until
> ADR-0130 has promoted the type it nests, so no lane implements this seam before
> ADR-0130 is merged.

**That clause exists because this ADR is deliberately half of a pair, and a
half-decision that does not say so reads as an underspecified whole.** Adversarial
review raised it as a blocker on the first round: an implementing change has no
model to build, because the tree at this ADR's base holds no ADR-0130. The
observation is correct and the fix is not to absorb the other half — deciding what
a notification *is* here would take the decision the leg-10 batch (#943) split into
its own lane precisely so that "what is worth saying" and "how it travels" could be
argued separately. What the review actually found is an unstated prerequisite, and
the corpus has a form for exactly that: ADR-0084 §11 named #473's evidence bound "as
a **prerequisite of the client lane**, not merely as context", for the same reason —
a dependency that binds a lane should bind it in a marked clause rather than in a
reader's inference. This ADR is second in its batch's merge order behind ADR-0130,
so the prerequisite is satisfied before any lane can act on it.

**Why the seam mints its own identifier instead of using the notification's.**
The acknowledgement is about *a delivery attempt*, and an attempt is a thing the
artifact knows nothing about: one entry can be delivered, leased, returned and
delivered again, and each of those writes is separately acknowledgeable by whoever
received it and by nobody else. A notification's own identity — if ADR-0130's
artifact even has one — could not carry that, because it is the same value on every
attempt. Minting here also keeps this ADR's surface decidable without knowing
whether the artifact carries an identity at all, which is the separation the two
lanes were split on.

> **Normative.** `budget` is honoured over the closed range from zero to
> `hub_max_notification_budget` (§5a). A `budget` of zero is an **immediate poll**:
> the hub answers at once with whatever is available, which may be nothing.

> **Normative.** A `budget` outside that range — negative, or above the bound — is
> refused as an ordinary correlated error naming the range. The hub does not
> silently clamp it in either direction.

> **Normative.** A `next_notification` request whose arguments are refused has **no
> effect on the outbox**. Arguments are validated before the acknowledgement is
> applied, before any entry is selected, and before any other outbox state changes;
> a refused request retires nothing, leases nothing and mints nothing.

**Validation has to precede the acknowledgement because this is the one method on
the surface that both refuses an argument and mutates state as a side effect of
another.** A device holding delivery `D` can send
`next_notification(acknowledging=D, budget=timedelta(seconds=-1))`. Without an
ordering rule, one implementation acknowledges and then refuses — reporting a failed
request while having permanently retired `D`, so the device's retry with a valid
budget finds the notification gone — and another validates first and leaves it
available. Two conforming hubs, one lost notification. Adversarial review found it
on the nineteenth round. The rule is ADR-0087 §7's "decode, then validate, then
measure" carried one step further into effects, and it covers a malformed argument
of any kind, not only an out-of-range duration.

**Both ends of the range needed stating and only one had it.** `timedelta` admits
zero and negative values and neither exceeds a maximum, so a caller could send
`timedelta(seconds=-1)` and one implementation would return an empty result while
another handed it to a timeout primitive and raised something undeclared — no common
conforming behaviour, which is the fifteenth round's finding.

**Zero is admitted rather than refused because it is the one out-of-range value that
means something.** A device that has just been opened by the owner wants to know
what is waiting *now*, not in five minutes, and an immediate poll is exactly that
call — the same request with the waiting removed. Refusing it would push every client
into faking it with a one-second budget, which is the same behaviour with worse
latency and an arbitrary constant in it.

**Clamping is the tempting answer for the upper end and it is the one the corpus
keeps refusing** — it is accepting-and-ignoring in a second costume, and ADR-0084
§2's argument against that transfers exactly: a client whose ninety-minute budget is
honoured as ninety seconds has been told, by acceptance, that its budget was
accepted.

> **Normative.** No argument of `next_notification` carries a device identity, and
> no lane may add one. Where this ADR's rules are per-device, the identity is the
> one ADR-0124 §4 established at admission, held per connection by the hub's
> listener, and it is never read from a payload.

> **Normative.** A loopback connection has no device identity and is not given a
> synthetic one. For §2's one-connection-per-device rule, all loopback connections
> count as a single local device.

**This is the finding that most nearly broke the seam, and answering it exactly is
worth more than answering it quickly.** Adversarial review observed on the third
round that `_dispatch` (`wire/server.py`) calls an engine method with nothing but
the decoded request arguments — `await getattr(engine, method)(**arguments)` — while
`Admission`, which holds ADR-0124 §4's identity, is connection-local in
`_serve_requests` and never reaches the engine. So a method declared as above cannot
tell two remote devices apart, and an identity *argument* would be a value taken
from the peer, which ADR-0124 §4 forbids in terms: the hub "may not take that
identity from anything the peer asserts."

**The resolution is that the rules needing identity are connection rules and the
rules on the method are not, and separating them is what makes the signature
right.** Take them one at a time:

- **§2's one delivery connection per device, and §5's sub-bound**, need the
  identity — and they are properties of *connections*, enforced where the
  connections and the `Admission` already are. Nothing has to travel to the engine.
- **§3's offer rule needs no identity at all**, which is easy to miss because it is
  phrased about devices. "An entry is offered to one device at a time" is delivered
  by the *lease*: an entry written to any caller is unavailable to every other
  caller until it is acknowledged or expires. One outbox, one lease per entry, and
  "one at a time" holds without the outbox ever knowing who asked.
- **§3's acknowledgement needs no identity either, but only because the identifier
  is a capability.** An earlier draft argued it needed none because a device naming
  another device's entry "acknowledges a delivery the owner has in fact received,
  which is the truth". That is false for an entry still leased and not yet shown,
  and adversarial review demonstrated it with a guessed decimal identifier on the
  twelfth round. What makes the argument work is the 128-bit half of `delivery_id`:
  the token went to exactly one device, so possession stands in for identity, and
  the engine can honour an acknowledgement without knowing who is asking.

**The loopback clause is stated because silence there would be read as a gap rather
than as an answer.** `admission is None` on that listener and ADR-0084 §2 declined
`SO_PEERCRED` as authorisation on it, so there is no identity to be had and none
should be invented. Nor is one needed: ADR-0084 §1's `0600` bit means every loopback
peer is the owner on the owner's own machine, so treating them as one local device
is not an approximation, it is the fact.

> **Normative.** `core/errors.py` gains one `AssistantError` subtype, and
> `next_notification` declares it as its failure alongside the `OversizedValueError`
> every method declares (ADR-0085 §9):
>
> `NotificationBudgetError(AssistantError)` — the request's `budget` is outside the
> range §4 honours: negative, or above `hub_max_notification_budget` (§5a).

> **Normative.** `NotificationBudgetError` carries **no structured state**. Its
> message names the requested budget and the permitted range, and it contributes no
> `details` object to an error payload.

**One type for both limbs, and the name says the range rather than one end of it.**
It was `NotificationBudgetTooLongError` until the fifteenth round established that
the lower end needed ruling too, and a "too long" error reporting a negative duration
would be a message that is false about the input it was raised on. A caller's remedy
is the same either way — send a budget in the range — so a second type would
distinguish two cases nobody branches on.

**The refusal was already required to be an ordinary correlated error and had no
vocabulary to be one in**, which is the sixth round's finding and is exactly the gap
ADR-0085 §9 exists to close: "A Protocol whose methods raise unnamed exceptions is
not a contract a conformance suite can hold anyone to." The wire's call-path
vocabulary is "exactly the `AssistantError` subtree" (§10a), and ADR-0124 §7 draws
the line it falls on the far side of — its lowercase refusal tokens "appear on the
handshake path and never on the call path".

**It is an ordinary engine refusal, and that is what keeps the surface honest.** The
budget is an *argument*, so an in-process engine has everything it needs to raise
this and a wire client's hub raises it from the same value. Nothing about it depends
on which side of the transport the caller stands, which is the substitutability
ADR-0084 §5 promoted the façade to a Protocol for. §2's poll conflict was the
condition that could not meet that test, and it is a connection close there rather
than a second type here — architecture review's finding, and the whole reason this
clause now names one type instead of two.

**Carrying no structured state is a decision, not an omission**, and the second
architecture finding is why it is stated as a clause. ADR-0085 §10a requires an
oversized error payload to travel with `details: null` and the client to reconstruct
the declared exception with its structured state absent and `details_elided=True`.
An error with fields must therefore be constructible *without* them and must say
what their absence means — the discipline `OversizedValueError` pays for because
ADR-0084 §4 obliges it to carry the limit and the field. Nothing obliges this one.
Its two numbers are what a caller reads, not what a caller branches on, so they
belong in the message where §10a's reduction cannot strand them: an error with no
`details` object is one there is no reduced form of, and the reconstruction contract
is satisfied by having nothing to reconstruct.

**The origin-key collision (§3) is deliberately not among these.** The enqueue is a
hub-internal call from a producer, not a request that crossed the wire, so its
outcome is reported to that caller and never rendered as a frame. Giving it an
`AssistantError` would put a type on the promoted surface that no client can ever
receive.

> **Normative.** Landing this seam bumps `PROTOCOL_VERSION`, and the obligation
> falls on the change that adds the method, in that same change (ADR-0124 §9).

**This is a consequence recorded, not a judgement made.** ADR-0124 §9's rule
reaches "any change to the promoted surface's method set" and its prose settles the
case in advance: "A sixteenth method on the promoted surface is a request an older
hub answers with a failure the client did not ask for… After the hop it is the
case ADR-0084 §3's exact-match rule exists for." Nothing in this seam gives it a
way out — a poll from a new client to an old hub is refused by `_dispatch` as a
method "this build's engine surface does not declare", which closes the connection
with no reply, and the operator sees a hub that hangs up rather than §3's message
naming both versions.

**And this is a live instance of the gap #891 holds.** ADR-0124 §9 ruled that
compliance with the bump rule "is a review obligation on any change to
`core/types.py`, to the promoted surface's method set, or to the wire encoding"
and that no mechanical check exists. This ADR adds to all three at once. The bump
is stated here so that the implementing lane inherits it as a written obligation
rather than as a rule it must remember to apply, which is the substitute available
until #891 lands and is not a substitute for it.

### 5. A delivery connection spends the hub's connection budget, and does not get a second one

> **Normative.** A delivery connection counts against `hub_max_connections` and
> `hub_max_pending_handshakes` exactly as any other connection does. No lane may
> give delivery its own connection budget.

> **Normative.** The hub bounds concurrent delivery connections by
> `hub_max_delivery_connections` (§5a), refused at load unless it is **strictly
> less than** `hub_max_connections`, so that a slot for an ordinary session always
> remains.

> **Normative.** The global capacity check and its claim happen in the **same step**
> as §2's per-device check and claim, over both parts of the shared state at once. A
> poll dispatches only if it obtains both; one that obtains neither or only one
> claims nothing and its connection closes under §2.

**Both clauses restate a mistake the corpus has already made once and caught
once.** ADR-0124 §7 required the remote listener to share the hub's ceilings and
said why: "a second listener is the natural place to double a budget by accident…
Two listeners each honouring the figure independently would mean the hub honours
neither." A long-lived poll is the same trap wearing different clothes — it is a
connection that is *supposed* to sit idle, so the reflex is to exempt it from a
ceiling written against peers that connect and stop sending. The exemption would be
wrong for exactly the reason the ceiling exists.

**The two claims are one step because a bound checked separately is a bound that can
be passed twice.** With seven of eight slots held, two devices polling concurrently
can each pass the capacity check and each claim its own per-device slot, leaving
nine — adversarial review's twenty-third round, and the sixth finding of the shape
§3's linearizability rule exists for. It is also why that rule's subject is now
*defined* rather than listed: each earlier statement of it named the state it knew
about, and each time the next round found shared state the naming had left out.

The second clause is the half a shared budget alone does not buy. Delivery
connections are long-lived and ordinary sessions are not, so without a sub-bound a
handful of pollers occupy every slot indefinitely and the owner's CLI cannot
connect at all — a hub that is unreachable for a reason that is not legible, which
is ADR-0083's ruling 4 failure. The strictly-less-than form mirrors
`Settings`' existing refusal of a `hub_max_pending_handshakes` above
`hub_max_connections`, and is validated in the same place and the same way.

**Revocation needs nothing new, and checking that it does not is the point of
saying so.** ADR-0124 §8's linearization is implemented in `_serve_requests` as
two `_check_live` calls, one at dispatch and one immediately before the write. A
poll dispatched by a live device and answered an hour later passes the second
check at the moment the notification is written — which is precisely the case §8's
write-side check was added for: "a request dispatched a moment before a revocation
may be awaiting a model provider for seconds; if the rule stopped at dispatch, the
hub would finish that work and write the answer to a device the owner has
expelled." A revoked device's outstanding poll therefore yields no notification,
and the entry's lease expires and returns it to the outbox.

### 5a. The figures, named here because naming them elsewhere is what ADR-0093 §5 forbids

> **Normative.** The five figures below are `Settings` fields with these defaults
> and these ranges, and a value outside a range is refused **at load**. None is
> nullable: a hub serving delivery with no lease, no outbox bound, no budget bound
> or no connection sub-bound has the failure the clause naming it exists to
> prevent, so "off" is not an available value.

| Field | Type | Default | Range |
| --- | --- | --- | --- |
| `hub_notification_lease` | duration | 120 s | `> 0` |
| `hub_notification_outbox_entries` | integer | 256 | `>= 1` |
| `hub_notification_outbox_bytes` | integer | 1 MiB | `>= hub_max_frame_bytes` |
| `hub_max_notification_budget` | duration | 300 s | `> 0` |
| `hub_max_delivery_connections` | integer | 8 | `>= 1`, and `< hub_max_connections` |

> **Normative.** `hub_notification_outbox_bytes` is refused unless it is at least
> `hub_max_frame_bytes`, and `hub_max_delivery_connections` is refused unless it is
> strictly below `hub_max_connections`. Both are checked at load, in the model
> validator that already orders `hub_max_pending_handshakes` against
> `hub_max_connections`.

**Naming them here is obligatory rather than tidy, and the first draft got it
wrong.** That draft cited "ADR-0093 §5's discipline" at four separate clauses and
left every figure to the implementing lane. ADR-0093 §5 forecloses exactly that
move in its own text: its figures "are therefore named in §7a rather than left to
its lane — **that rule cannot be invoked here and satisfied elsewhere**." Behind it
stands ADR-0074 §9.3's reason, quoted there: "a 'bounded default' with no figure is
two conforming stores handing the same continuation different history." Two
conforming hubs with different retention, capacity and availability is the same
failure with the nouns changed. Adversarial review found it on the second round.

**Where each figure comes from.**

- **`hub_notification_lease` at 120 s.** The lease only binds a device that took a
  delivery and did not acknowledge it, because a live device acknowledges on its
  very next poll. So the figure is not a latency budget for the ordinary case; it is
  how long a *dead* device withholds a notification from a live one. Two minutes is
  long enough that a device briefly losing its network does not cause a duplicate
  telling, and short enough that a laptop closed mid-notification does not hide it
  for the rest of the morning.
- **`hub_notification_outbox_entries` at 256.** A ceiling on how many unheard
  notifications survive an absence. At the rate a proactivity policy that "earns
  its place" should be producing, this is days of backlog, so reaching it means
  either a long absence or a producer misbehaving — and both are cases where the
  oldest entries are the ones worth least.
- **`hub_notification_outbox_bytes` at 1 MiB, floored at `hub_max_frame_bytes`.**
  The byte bound is what stops a few large notifications defeating the count bound.
  The floor is the constraint that makes it a bound rather than a trap: an outbox
  smaller than one frame could hold no entry a device could receive, and would
  evict every notification the instant it arrived — a hub that silently delivers
  nothing, which is this leg's whole failure produced by a config typo.
- **`hub_max_notification_budget` at 300 s.** The ceiling on how long one poll may
  occupy a connection. Five minutes keeps a device's handshake rate negligible while
  bounding how long a delivery connection is unreclaimable after a device goes away
  without closing.
- **`hub_max_delivery_connections` at 8, strictly below `hub_max_connections`.**
  Eight is generous against a single-user deployment's device count and leaves 56 of
  the default 64 for ordinary sessions. The strict inequality is the load-bearing
  half: it is what guarantees a slot for the owner's CLI, so a hub saturated with
  pollers is still a hub the owner can talk to.

### 6. ADR-0124 §7's credential-type clause binds the remote listener (#934)

> **Normative.** ADR-0124 §7's clause "The credential member is a JSON string, or
> it is absent" is a rule of **the remote admission rule**, and it binds the remote
> listener alone. On the loopback listener ADR-0084 §2 governs unchanged, and a
> present JSON `null` is a client saying it carries no credential: it is admitted,
> as an absent member and an empty string are.

**Read the section's own structure and the answer is already there, except in one
place where it is not.** ADR-0124 §7 is titled "The remote admission rule". Its
first two clauses open "On the remote listener"; its fourth states that "ADR-0084
§2's rule is unchanged on the loopback transport". Only the third omits the
qualifier, and its supporting paragraph shows the author believed loopback needed
no rule: "`read_connect` (`wire/envelope.py`) refuses anything not in `(None, "")`,
so on loopback an object, a boolean or a number is already refused and the question
never arises."

**That sentence is true of an object, a boolean and a number, and false of
`null`** — `null` decodes to `None`, which is *in* that tuple. So the belief that
made the qualifier unnecessary is wrong on exactly one value, and the clause's wide
reading is therefore reachable by a careful reader rather than only a careless one.
#934 is the record of noticing.

**Admitting is right, and it is ADR-0124 §7's own principle that says so.** §7
states the principle in one sentence — "**Admission never asserts a check that did
not happen**" — and derives its two opposite rules from it. Apply it here: a
loopback client sending `"credential": null` is stating that it carries none, and
admitting it asserts nothing about any check. The `0600` bit is what restricts
connection on that transport, exactly as ADR-0084 §2 said, and nothing about a
`null` weakens it.

**Refusing would cost a rule to state it in, and there is no honest one
available.** §7 froze the only loopback code that exists: "there a non-empty
credential is still refused with `credential_not_supported`" — and a `null` is not
a non-empty credential. Refusing under that code would report a reason that is
false; minting a new code would put a refusal on the loopback handshake for a value
that asserts nothing. Both are worse than the status quo, which is what #933's fix
lane concluded when it left the behaviour alone and pinned it by test
(`tests/wire/test_remote_connect.py::test_a_null_credential_is_still_nothing_on_the_loopback_transport`).

**No code changes and that is the intended outcome.** `read_connect` already
carries this reading with its reasoning attached — "A present ``null`` stays on the
'carries nothing' side here" — and `read_remote_connect` already carries the
opposite one for the remote listener. What was missing was a ratified sentence
saying which of the two readings of §7 the tree is implementing. §9 records this as
a **partial supersession** of ADR-0124 §7's credential-type clause, because a reader
holding only ADR-0124 could read that clause more widely than it now holds, which
is ADR-0070 §1's second limb.

### 7. Whoever answers the overlay agent socket is authenticated from the kernel (#939)

> **Normative.** After connecting to the overlay agent's socket and before writing
> anything to it, the querying process reads the peer's credentials from the kernel
> and refuses unless the peer's effective uid is `0` or its own. It refuses on a
> platform that exposes no peer-credential call, rather than proceeding
> unauthenticated.

> **Normative.** The rule binds both ends of the hop and every agent socket path
> alike — the packaged defaults in `TAILSCALE_SOCKETS` and any path an operator
> configures. No lane may apply it to a configured path and not to a default one.

**This closes a gap the filesystem checks were never able to close, and the corpus
has already said so twice.** ADR-0084 §1 is quoted verbatim in `wire/peer.py`:
filesystem checks are "a walk over topology the operator controls, and a walk can
be wrong — a bind mount, an ACL, a symlinked ancestor", and what closes the hole is
reading the peer's credentials from the kernel after connecting, which is "free of
the time-of-check time-of-use gap a pre-connect `stat` of the socket would have".
`service/datadir.py`'s module docstring restates the same position for the data
directory and assigns the fix to "the transport lane". The adversarial review on
PR #936 then exhibited the concrete attack — a POSIX ACL granting an untrusted user
write and search access through an otherwise-conforming `0700` directory, after
which that user replaces the socket before `open_unix_connection()` and supplies
overlay identities for remote admission.

**Why the rule is "root or us" and not "root".** `tailscaled` runs as root in the
ordinary deployment, so uid 0 is the answer that must be admitted. But ADR-0124
§11's own validation plan and the namespace #919 used both run the agent as the
invoking user, and a test seam necessarily does. Admitting our own euid costs
nothing security can measure — a process running as us could replace our own files
regardless — and refusing it would make the rule unimplementable in the deployment
the ADR that needs it was validated in. This is the same shape as `wire/custody.py`'s
ownership rule, which is why it reads as the obvious candidate in #939 too.

**Why it belongs in this ADR rather than being declined to a later one.** Every
delivery connection is admitted on one answer from the agent (ADR-0124 §4), and
§2 above makes that connection long-lived: a device admitted on a forged identity
does not merely get a session, it gets a standing channel into which the hub writes
the owner's material as it is produced. The seam that raises the value of the
identity is the right place to close the gap in how the identity is obtained.

**Where it attaches, and the tree has moved since #939 was filed.** #939 says "The
client half has the same shape — see #937", and both halves of that are now stale:
#937 turned out to be about the client agent's *configurability* and is closed, and
since `refactor(wire): move the agent-socket custody guard where both ends can
reach it` the filesystem guard lives in `wire/custody.py` with the agent client in
`wire/overlay.py`, which `service/overlay.py` imports. So the rule has **one**
implementation site — the `_request` connect path in `wire/overlay.py` — reached by
both ends, and `wire/peer.py`'s `peer_uid` already supplies the read and already
fails closed where the platform cannot answer. There is nothing to design; there was
only a rule to ratify.

**This does not weaken the filesystem checks and does not replace them.** They stay
as `service/datadir.py` describes them — defence in depth — and this clause is the
one that makes the posture closed rather than merely deep.

### 8. What this ADR does not decide

- **What a notification is, who may produce one, and what earns an interruption.**
  ADR-0130's, entirely. This seam carries a disposed notification and never
  inspects one.
- **Which device the owner is actually at.** §3 rules first-to-ask and says it is
  crude. The successor is a device as a context facet and a device-scoped
  permission input, which ADR-0124 §10 already defers and #920 holds. A later ADR
  replacing §3's routing rule replaces one clause and leaves the outbox alone.
- **What content a device may receive.** Every enrolled device is the owner's under
  ADR-0099 §1's single principal and ADR-0124 §5's rule that a device "is not a
  principal, not a spoke, and not a grant". A per-device content policy is the
  grant model (#629), which ADR-0094 §3 and ADR-0124 §5 both decline, and no lane
  may read this seam as supplying one.
- **How pull rides the connection.** ADR-0094 §10 defers a *spoke-to-hub* pull —
  the hub asking a sensor for released material. §1's clause forbids the hub
  initiating, and nothing here supplies the request/response shape that deferral
  needs; a poll that carries a notification outward is not a pull that reaches
  edge state.
- **Streaming and progress.** ADR-0042 §5 and ADR-0084 §11 defer it "until a
  progress-emitting stage exists". A long poll is a request whose answer is late,
  not a stream, and it consumes none of the correlation id's reserved future.
- **The mechanical check on `PROTOCOL_VERSION`.** #891, unchanged and unmoved.
  §4 makes this seam an instance of the gap, not a discharge of it.
- **The custody handoff ADR-0094 §10 defers.** That is material travelling
  *inward*, from a spoke the hub cannot see the state of. §9 records why §10a's
  clauses do not bind here and why their discipline was adopted anyway.
- **A second hub, and a device that is not the owner's.** ADR-0124 §10's clause is
  untouched.

### 9. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in this ADR's text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?

**ADR-0124 §7's credential-type clause is partially superseded** — §6 above. A
reader holding only ADR-0124 could read "The credential member is a JSON string,
or it is absent" as a statement about the connect schema, binding both listeners,
and the clause's own supporting paragraph does not close that reading because its
factual premise is wrong about `null`. §6 narrows the clause to the remote
listener. That is ADR-0070 §1's second limb — a clause read more widely than it now
holds — so it is a supersession and not an amendment, and it is **partial**: §7's
other four clauses, the whole of the two-fact admission rule, the distinguished
refusals, the shared ceilings and the refusal-code form are untouched and stay
accepted. ADR-0124's Status line and a dated header note record it; not one word of
its Decision text is edited.

**No record is owed on ADR-0124 §4, and the reason is worth stating rather than
assumed.** §7 above *adds* a condition to the overlay-agent seam where §4 was
silent — §4 requires the hub to obtain the identity from the agent "over a local
interface" and says nothing about who may answer. A reader holding only §4 was not
led to act *contrary* to anything; they were led to act incompletely. That is the
stacked-addition category ADR-0083 §15 established and ADR-0084 §12 applied, and
treating it as a supersession would make every later ADR that tightens an
unaddressed corner a supersession of the ADR that did not address it.

**No record is owed on ADR-0094 §2.** §1 above decides "how pull rides the
connection" for the outward direction only, which is what §2 said it was leaving
open — "the mechanism is an additive wire decision owing its own ADR (§10), and
this section decides only the direction, which that decision must not reverse". The
direction is not reversed; it is the premise §1 is built on. A deferral discharged
by the kind of ADR it named is a stacked addition (ADR-0084 §12's treatment of
ADR-0083).

**ADR-0084 §3's count of the decoded-frame close as the one exception is partially
superseded**, and an earlier draft of this section wrongly said no record was owed.
§3's second bullet gives a decoded frame a typed error "provided it is not itself a
violation of the connection's own rules", and its third names "**the one exception
on this side**". §2 above adds a second connection-level rule and closes on its
violation, so a reader holding only ADR-0084 — handed a second delivery poll —
answers with a typed error where this ADR closes. That is ADR-0070 §1's first limb.
Architecture review found it on the tenth round, after the same review's ninth-round
finding had moved §2 from a typed error to a close in the first place; the second
finding is the cost of the first, correctly priced.

**What fails is the enumeration and not the rule**, which is why the scope is
written as narrowly as it is. §3's proviso — a decoded frame that violates the
connection's own rules — is untouched and is the very test §2's rule meets; what was
wrong was a belief, true when written, that seriality was the only such rule. §3's
*reason* for its own exception does not transfer and this ADR does not pretend it
does: an overlapping request is closed because a correlated error would carry an id
the client must reject, and a second poll arrives on its own connection with its own
id. It is closed for §2's reason instead. Everything else in §3 stands and this ADR
rests on nearly all of it — the framing, the codec, the envelope, the two serial
rules, the correlation id and its unspent reserve, the frame ceiling and the version
freeze. ADR-0084's Status line and a dated header note carry the record; not one
word of its Decision text is edited.

**No record is owed on ADR-0124 §1, and that is the substantive finding rather
than a formality.** §1's accountability bullet — "There is no path by which either
transmits something nobody asked for" — stays true because §1 above chose the shape
that keeps it true. Had this ADR chosen server push, §1 would have needed
superseding on the axis ADR-0017 §4 says egress accountability is measured by.

**No record is owed on ADR-0124 §9 or §10.** §9 is applied as written (§4 above);
§10's three clauses are honoured — the hub still does not dial, this ADR *is* the
contract ADR §10 says an implementing lane owes, and §10's prohibition on reading
ADR-0124 as deciding the delivery seam is satisfied by this ADR deciding it
elsewhere.

**No record is owed on ADR-0094 §10a's custody clauses.** Their subject is "a
spoke's unresolved submissions" — material arriving at the hub from an edge whose
state the hub cannot see. This seam runs the other way: the hub holds the material,
the hub is the durable party, and the device is the one that may vanish. The
clauses are not met because they are not engaged. §3 above adopts the analogue of
all four by choice — custody transferring at a single durable commit and not
before, a terminal outcome in finite time via a lease with a named duration, an
aggregate bound by count and by bytes with a total eviction rule, and durability
across a restart stated rather than left silent — and says so at each, so a reader
does not have to infer whether the resemblance was noticed. Adversarial review's
first round is why the custody one is a clause: this ADR claimed the discipline
before it applied it at the point where it bites.

**This ADR is marked under ADR-0089.** Every obligation it imposes is a marked
clause; unmarked text explains what a marked clause means and supplies no
obligation of its own.

## Consequences

**What gets easier.** Leg 10's delivery lane has a shape it can build without
touching the envelope: one method, one type, one durable queue, one long-lived
connection, and no change to framing, codec, correlation or the serial rule. The
hub's existing revocation linearization covers a poll answered an hour after it was
dispatched, with no new check. A client is still stateless, so a notifier that
crashes reconnects and re-polls, and at-least-once means it loses nothing by doing
so.

**What gets harder.** `PROTOCOL_VERSION` moves to 3, which means the hop's two
halves must be upgraded together — the deployment ADR-0124 §11 validates by hand on
two commodity devices, now with a version mismatch to notice on the next run. A
second connection per notifying device makes the hub's connection accounting matter
in a way one CLI never did, which is why §5 exists. And the outbox is durable state
in the data directory, so it is state a backup must carry and a purge must destroy —
#883's backup lane and ADR-0126's destruction of the cold data directory both
acquire a new object to know about, and neither is changed by this ADR beyond
having one more thing in the directory they already govern.

**What would trigger revisiting this.** A second spoke profile that needs the hub
to reach it for something other than a notification — an actuator being told to
act, which ADR-0094 §1's capability profiles anticipate — would test whether "one
method, one queue" generalises or whether the seam wants a verb. A device that is
genuinely absent for days, so that the outbox's bound is reached routinely rather
than exceptionally, would make §3's drop-oldest rule visible as a product
behaviour rather than a safety valve. And #920's device-as-context-facet is the
decision that replaces §3's first-to-ask routing; when it lands, that clause is the
one to supersede.

**What this does not prove.** Nothing here is validated. ADR-0124 §11's plan tests
the hop and does not test a notification; the leg's own QA run is where "the hub
noticed something overnight and the owner saw it in the morning" is either observed
or not. This ADR is the shape that makes such a run possible, and a shape is not
evidence.

## Alternatives considered

**A `notify` frame the hub writes unsolicited.** The shape everyone reaches for
first, and the one that costs three ratified clauses: a new frame kind and a
client demultiplexer (the multiplexing ADR-0084 §3 deferred), a rule for an
unsolicited frame arriving while a request is outstanding (the one input §3 says
has exactly one answer), and ADR-0124 §1's "no path by which either transmits
something nobody asked for" re-argued. It buys lower latency than a long poll and
lower latency is not the constraint — a notification that arrives within a poll
budget is a notification that arrives.

**The hub connects to the device.** ADR-0094 §2 forbids it in a marked clause and
ADR-0124 §10 restates the prohibition specifically because the overlay makes it
easy. Not considered further, and named here only so the record shows it was the
first thing checked and not the thing nobody thought of.

**Polling on the device's ordinary session connection.** Rejected because
ADR-0084 §3 makes it not merely inelegant but broken: the first `converse` the
owner types while a poll is outstanding is a protocol violation that closes the
connection. §2 turns the constraint into a stated rule so that no implementation
discovers it the hard way.

**Short polls on a timer instead of a long poll.** A device asking every thirty
seconds needs no budget argument and no long-lived connection, so §5's sub-bound
would be unnecessary. It was rejected on the deployment ADR-0124 §11 describes:
a laptop and a phone doing a connect handshake — including an overlay agent query
per §4 — every thirty seconds, forever, to learn nothing, is a duty cycle cost paid
continuously for a message that arrives a few times a day. The long poll pays one
handshake per poll budget and the hub answers the instant it has something, which
is both cheaper and faster.

**Per-device fan-out instead of one outbox for the owner.** Delivering every
notification to every enrolled device removes the routing question entirely and
removes the lease with it. Rejected because it multiplies the interruption ADR-0130
exists to ration by the number of devices the owner happens to own, which makes the
policy above it weaker every time the owner enrols a laptop.

**At-most-once: the hub retires an entry when it writes it.** Simpler — no lease,
no acknowledgement, no `acknowledging` argument. Rejected because the failure it
chooses is the one that matters: a device that dies between the hub's write and the
notification reaching a screen loses it silently and forever, which is the exact
failure this leg exists to close, arriving through the mechanism meant to close it.

**Deciding `PROTOCOL_VERSION` differently.** Not available. ADR-0124 §9's rule is
ratified and reaches "any change to the promoted surface's method set" explicitly,
with prose that names the adding-a-method case and calls the bump "the honest
consequence rather than an oversight". §4 records the consequence; it does not
weigh it.

**Declining #939 to a later ADR.** The narrower reading of this lane's scope, and
it was the starting position. Rejected because §2's long-lived delivery connection
is what raises the stakes on the agent's answer: an identity obtained once now
gates a standing channel rather than a single session, so the seam that raises the
value is the seam that owes the closure. The rule was also fully specified in #939
and its implementation site is one function; declining would have deferred a
ratification, not a design.
