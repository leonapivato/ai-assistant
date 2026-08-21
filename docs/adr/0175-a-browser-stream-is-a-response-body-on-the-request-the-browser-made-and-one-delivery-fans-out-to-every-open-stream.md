# 175. A browser stream is a response body on the request the browser made, and one delivery fans out to every open stream

- Status: Proposed
- Date: 2026-08-21

- **This is `track:web-client` milestone 14's surface decision** (#1230). Its
  exit test is *a conversation and a pushed notification, end to end, on a
  phone*, and three ratified deferrals converge on it: ADR-0168 §12's
  browser-facing surface "and whether a push carrier such as a WebSocket is among
  them", ADR-0168 §12's fan-out of one delivery to several browsers — "it fires
  with milestone 14, which is the first consumer of that seam and the decision
  that will have a browser surface in hand" — and ADR-0173 §12's and ADR-0174
  §11's restatements of the first. This decision discharges all three.
- **No implementation lands with it.** No `src/`, no `tests/`.
- **It decides no `core/protocols.py` and no `core/types.py` surface** (§10), so
  golden rule 5 is not triggered. It adds one `Settings` field (§8), which is
  contract surface in ADR-0054's sense — the position ADR-0084 §3 was in for its
  four transport figures, ADR-0168 §8 for its ten and ADR-0174 §8 for its three.
- **It partially supersedes one ADR, in one clause, and that record rides this
  change** (ADR-0070 §1, ADR-0082 §1, ADR-0083 §15): **ADR-0168 §8's
  read-deadline sentence**, "The gateway closes it `gateway_read_timeout` after
  the last complete request it carried", only as it reaches a connection carrying
  a response the gateway has not finished writing. A reader holding only §8 ends
  every stream this ADR defines after thirty seconds. §12 applies ADR-0070 §1's
  test clause by clause to every other ADR a reader might expect this to falsify
  and finds no further record owed.
- **Its required review set is adversarial *and* architecture.** It decides the
  carrier on the wire seat, the consumption of a ratified delivery seam and a
  closed enumeration of which promoted operations a browser reaches — the pair
  ADR-0168 and ADR-0174 each took both lenses for, and `CONTRIBUTING.md` makes a
  change contract-surface when it is the ADR deciding that surface.
- **The owner's secure-context ruling is what makes this decision available, and
  it is cited rather than assumed.** On 2026-08-21 the owner ruled on #1230 that
  the exit test's pushed notification is **in-page** — delivered over the delivery
  connection and rendered inside the open page — and that an operating-system
  notification is not required. ADR-0174 §7's stop condition on this lane is
  discharged by that ruling; TLS and every secure-context capability stay deferred
  to ADR-0174 §7's own named trigger (§10).
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-21**,
  the durability form ADR-0100 established. Refs #1230.

## Context

### What milestone 14 asks for, and what is already ruled

#1230's milestone 14 reads: "conversation and notifications — streaming chat;
conversation list / resume / forget; the delivery connection (`next_notification`,
ADR-0131) held open — the first push consumer."

Almost every mechanism that sentence names is ratified and most of it is built.

- **The gateway exists.** ADR-0168 seats it as a spoke of the client profile that
  reaches the hub through the promoted `AssistantEngine` Protocol and authors
  nothing; `src/ai_assistant/interfaces/gateway/` is on `main`, reached by
  `assistant gateway`, serving three paths — a document and its two assets, the
  bootstrap exchange, and one turn.
- **A browser is admitted.** ADR-0168 §§3–7 mint and verify a two-value web
  session; ADR-0172 rules the ADR-0004 exemptions that session needs and makes
  them conditional on ADR-0168's own storage and record clauses.
- **A phone can reach it.** ADR-0174 authorises the fourth egress boundary — the
  gateway's remote browser listener and the front end it serves — off unless
  configured on, admitted on an attested overlay identity *and* the session.
- **The hub streams.** ADR-0173 gives `FrameKind.CHUNK`, the `ReplyChunk` type
  and `converse_streaming`, and rules that the terminal result frame is still the
  answer.
- **The hub delivers.** ADR-0131 gives `next_notification`, the durable outbox,
  the per-device delivery slot and the `delivery_id` capability. It is
  **fully built and entirely unconsumed**: nothing in `src/` calls it outside the
  wire client and the canonical fake, and `tests/interfaces/test_cli.py` records
  that its absence from the command line is deliberate, because "putting it on a
  person's command line would let a human consume the delivery a device is owed."

So this decision is not a transport, an admission scheme or a contract. It is
what happens on the browser's side of an adapter that exists, for two message
shapes the hub can now produce and the browser has no way to receive.

### The three deferrals that land here, read rather than remembered

ADR-0168 §12 deferred "the browser-facing surface itself — the request shapes,
the paths, the document, and whether a push carrier such as a WebSocket is among
them", on the ground that "milestone 13's behaviour needs no server-initiated
browser message at all, and adding a carrier for one before something emits it is
the unspiked seam ADR-0042 §5 and ADR-0084 §11 have twice declined." It deferred
the fan-out separately and by name.

ADR-0173 §12 then examined that deferral's own condition and found it **still
unmet**, in terms: "Something now emits — but what it emits is **solicited**, so
the condition §12 was guarding against still has not arrived. A gateway can carry
every frame this ADR defines without any server-initiated browser message
existing." Streaming, hub-side, is an answer to a request the client made.

**That reading is correct and it is worth being exact about what it leaves,
because the brief for this lane had it the other way round.** ADR-0173 did not
fire ADR-0168 §12's trigger, and neither does ADR-0131. Delivery is a long poll —
"a notification travels as an answer the device asked for" is that ADR's whole
title — so nothing hub-side is unsolicited either, and §1 of it forbids anything
becoming so. What actually brings the question here is not that something started
pushing. It is that **milestone 14 is the first consumer of both seams at the
browser edge**, and both ADR-0168 §12 and ADR-0174 §11 name this milestone as
where the choice is made. The seam is spiked now in the sense ADR-0042 §5 asked
for — there is something to put on the carrier — without any clause of any ADR
having been falsified in the interval.

### What a browser can actually present, which is the fact that decides the carrier

ADR-0168 §6 is normative about how a session travels, and its clause is short:

> The header half is held in browser storage scoped to **scheme, host and port**
> and shared across that origin's tabs, and it is sent only as a request header
> the front end sets. It is never placed in a cookie, in a URL, or in storage
> that outlives the origin's own scope.

And §6's admission rule is that both halves are required: "Neither admits a
request alone, and a request carrying one and not the other is refused exactly as
one carrying neither is."

Run the three candidate carriers against that.

- **`WebSocket`.** Its constructor takes a URL and a subprotocol list. A page
  cannot set a request header on the opening handshake — there is no argument for
  one and no interface that supplies one. The browser attaches the cookie half
  (the handshake is a request to the same origin, so `SameSite=Strict` is
  satisfied), and the header half has nowhere to go but the URL, which §6 forbids
  in terms, or the subprotocol field, which is a protocol-negotiation value echoed
  back in the response. So a socket is admitted on one half or on a credential in
  a URL, and §6 refuses both.
- **`EventSource`.** Same defect and less room to argue about it: the constructor
  takes a URL and one boolean, and there is no interface for a request header at
  all.
- **An ordinary request whose response body streams.** `fetch` sets whatever
  headers the front end gives it and exposes the response body as a readable
  stream, so both halves travel exactly as §6 requires and the surface differs
  from the one shipped in milestone 13 only in that a response is written in more
  than one piece.

**So the carrier is not a preference between three workable options.** Two of the
three cannot present the credential the ratified session design requires, and
admitting either would take a supersession of ADR-0168 §6 — a clause whose two
halves exist because a single-value design "would have shipped the exact bypass
§3's session exists to prevent." That supersession would be bought to obtain a
bidirectional carrier for a surface in which nothing is bidirectional.

The content security policy ADR-0168 §6 requires does *not* decide this, and
saying so keeps a weaker argument out of the record: `connect-src 'self'` admits a
same-origin `fetch`, and admits a same-origin socket too on the reading current
browsers implement. The policy is neutral here; the session clause is not.

### One delivery slot, and what a gateway can and cannot do with it

ADR-0131 §2 gives a device at most one delivery connection, ADR-0131 §4 keeps
every device identity out of the engine, and `wire/server.py` implements the slot
as a check-and-claim taken before dispatch, keyed on `admission.device()` — which
is `None` on the loopback listener, an identity rather than a missing one,
because the `0600` bit makes every loopback peer the owner.

A gateway is one device. So the arithmetic ADR-0168 §12 recorded as inherited is
exact: however many browsers a gateway serves, it holds one poll, and what it
does with the one answer is the whole of the fan-out question.

Two facts bound how large that question is in this milestone, and both are worth
stating before the decision rather than after.

- **There is at most one live session.** ADR-0168 §5 mints one bootstrap value
  per process and one session from it; ADR-0174 §9 declines to relax that and
  shows the exit test reachable under it. #1320 records `gateway_max_sessions` as
  inert for that reason. So the fan-out this decision must rule is one delivery
  to the several *connections* of one browser — its tabs — and not to several
  browsers.
- **The gateway holds no store.** ADR-0168 §1 forbids it opening one and ADR-0094
  §9 permits edge state only where it is bounded in size and in age and destroyed
  continuously. A gateway that buffered notifications for browsers that are not
  watching would be building the durable outbox ADR-0131 §3 already built, one hop
  further out and without any of its bounds.

### What the tree's browser edge is today

`interfaces/gateway/http.py` is a hand-written HTTP/1.1 reader and renderer:
`Response.body` is `bytes`, every response carries a fixed `Content-Length`, and
`Transfer-Encoding` on a *request* is refused rather than parsed. `server.py`
classifies a request into ADR-0168 §6's four kinds from its method and path alone,
and one path — `POST /ask` — reaches the engine, on the single call
`self._engine.converse(utterance, timeout=_TURN_BUDGET, conversation_id=conversation)`
under a sixty-second module constant. `app.js` disables its button for the whole
turn and inserts every value the hub returned with `textContent`.

So the browser's interaction model today is one blocking request per turn with no
progress signal and no path by which anything reaches it between turns. That is
precisely the two gaps this decision fills, and it fills them without a second
kind of connection.

## Decision

We will carry every message the gateway sends a browser on a **stream** — the
body of the response to one ordinary request the browser made — serve **no**
socket and **no** upgrade, hold a `next_notification` poll while and only while a
browser is listening, write each delivery to **every** open delivery stream while
keeping the `delivery_id` inside the gateway, and expose a **closed** enumeration
of five promoted operations to the browser.

### 1. A stream is a response body on the request the browser made

> **Normative.** Every message the gateway sends a browser travels on a
> **stream**: the body of the response to one ordinary HTTP request that browser
> made. The browser establishes it, and the gateway writes on it only in answer to
> that request.

> **Normative.** One stream answers one request and carries no second exchange.
> The gateway correlates nothing on a stream, multiplexes nothing on one, and
> carries no identifier by which a value on one is matched to a request other than
> the one it answers. A browser wanting two things in flight makes two requests.

> **Normative.** The gateway serves no WebSocket, offers no protocol upgrade and
> honours no `Upgrade` header, and serves nothing a browser reaches with
> `EventSource`. ADR-0168 §7's refusal of a connection upgrade carrying a foreign
> `Origin` is applied and is not read as authorising one carrying the gateway's
> own.

> **Normative.** The gateway opens no connection to a browser. ADR-0174 §10's
> direction rule binds unchanged and is what this section implements at the
> surface: an overlay address for a browsing device is not permission to initiate
> a connection to it, and no clause of this ADR authorises one.

**The decisive argument is ADR-0168 §6's, and it is mechanical rather than
architectural.** §6 requires both halves of a session on every admitted request
and requires the header half to travel "only as a request header the front end
sets", never in a URL. A `WebSocket` handshake and an `EventSource` request are
the two requests a browser can make on which the page cannot set a header at all,
so on either one the header half has nowhere to go that §6 admits — and a request
carrying the cookie half alone is one §6 refuses exactly as it refuses one
carrying neither. Choosing a socket therefore means superseding the clause whose
absence, ADR-0168 §6 records, "would have shipped the exact bypass §3's session
exists to prevent." No milestone-14 behaviour needs what the supersession would
buy.

**The second argument is that a socket would make the gateway author something,
and golden rule 3 is the rule it would author against.** A socket carrying more
than one exchange needs a correlation scheme at the browser edge — an identifier
matching a value to the request that provoked it. That is multiplexing, which
ADR-0084 §3 deferred and which ADR-0173 §1 declines to add in terms: "This ADR
adds no multiplexing, and no lane cites it toward any." A gateway that invents one
is composing behaviour the promoted engine surface does not offer, which ADR-0168
§1 forbids by name. And a socket used *serially* — one exchange at a time — buys
nothing a response body does not already give, at the cost of a framing
implementation, a ping/pong policy and a close-code vocabulary.

**The third is that the shape already matches, one hop in.** ADR-0173 §1 makes a
streamed answer "one request frame, carrying one correlation id, answered by zero
or more chunk frames followed by exactly one terminal frame". A response body
written in pieces on the request that provoked it is that sequence with the
framing changed, which makes the gateway a translator of one frame into one value
— the thinnest thing it can be, and what ADR-0168 §1's biconditional was written
to keep it.

**What this costs is stated rather than smoothed over.** A response body that
streams is not what `interfaces/gateway/http.py` renders today: `Response.body` is
`bytes` and every response carries a `Content-Length`. The implementing lane grows
a second response shape and the chunked framing to carry it, and that is the
largest single piece of work this decision creates. It is smaller than a socket by
a wide margin, and it is confined to one module.

**And one property is a genuine loss, named here rather than discovered in
milestone 21.** A response body streams from the gateway to the browser and not
back, so this carrier supplies no path for a browser to stream *to* the gateway —
which is what `track:voice`'s first rung (#1318) asked this track not to preclude
when it filed microphone capture as a candidate input. It is not precluded and it
is not supplied: §10 defers it with its trigger, and notes that it is gated twice
over, since microphone capture is a secure-context capability and ADR-0174 §7
already stops a lane that needs one.

### 2. What a stream carries, and the one discriminator

> **Normative.** A stream carries a sequence of values, each of exactly one
> **kind**, and a reader resolves a value's kind from a discriminator the value
> itself carries and never by inspecting what the value contains. The kinds are
> fixed in advance, and no value carries a second claim about what it is.

> **Normative.** Every stream ends in exactly one of two ways, and a reader tells
> them apart from the stream alone: the gateway wrote a **terminal** value, or the
> body ended without one. A reader that reached a terminal value has the whole of
> what the gateway sent; a reader that did not has a transport failure and the
> front end reports it as one, which is ADR-0168 §9's distinction reaching the
> browser.

> **Normative.** The exact framing of a value on a stream, the media type a stream
> is served with, and the paths the surface uses are the implementing lane's, on
> ADR-0168 §12's own division: they are not `core` surface, they are not a
> Protocol, and the front end and the gateway ship and version in one distribution
> (ADR-0168 §10). This ADR fixes the two clauses above and nothing further about
> the bytes.

**The discriminator clause is ADR-0173 §2's argument taken at the second edge.**
That section refused a sequence number and a final-frame flag on the ground that
"a frame that is a chunk by kind and final by flag is two answers to one question",
and ADR-0173 §4 requires a reader to resolve its yielded union "by frame kind and
never by inspecting a payload". A browser reading a stream is the second reader of
the same sequence, and a surface that made it guess from a payload's shape would
reintroduce, in the half of the system that renders untrusted model output, exactly
the ambiguity the wire refuses.

**Deciding the framing here would be deciding somebody else's question.** ADR-0168
§12 hands the request shapes and paths to the implementing lane and gives the
reason — a surface that versions with its own bundle in one distribution owes no
ADR. What is decided here is what a *carrier* is and what a reader may rely on,
because those are the parts other ratified clauses turn on. A clause naming a media
type would be this ADR reaching past its own subject.

### 3. A turn's answer streams, and the terminal value is still the answer

> **Normative.** A browser's streamed turn is one request, answered by a stream
> carrying the values ADR-0173 §1's frames carry, in the order they arrived: one
> value per `ReplyChunk`, then one terminal value carrying the `TurnOutcome`, or
> one terminal value carrying the fault the exchange ended in.

> **Normative.** ADR-0173 §3 binds at this edge unchanged. The terminal
> `TurnOutcome`'s `reply` is the answer; where a rendered chunk sequence and it
> disagree, the front end renders the terminal `reply`; and no front end treats an
> accumulated chunk sequence as the record of what the assistant said.

> **Normative.** Both turn entries reach the browser and the gateway never
> substitutes one for the other. A streamed turn that composed no answer is
> rendered as ADR-0173 §10 requires — the step account it carries, plus a statement
> that the answer is incomplete — and is not re-asked as `converse` by the gateway;
> a turn the browser asked for whole is answered by `converse` and never from a
> stream.

**Keeping the non-streaming entry on this surface is a decision and not inertia,
and ADR-0173 §5 is why it matters.** That section rules that a configured route
which cannot stream "is a `ModelError` from the call — before any delta — and the
pass degrades into §6's pre-commit shape". So on a build whose provider does not
stream, *every* streamed turn returns `reply` `None` with `reply_degraded` `True`.
A browser surface offering only the streaming entry would answer nothing at all on
such a build, while the CLI on the same machine answered normally — which is
ADR-0083's ruling 4 failure produced by a surface choice. Keeping `converse` is
what leaves the owner a path that works, and ADR-0173 §4 kept it on the promoted
surface for the neighbouring reason.

**The gateway does not choose between them, and refusing it that is the point.**
An automatic fallback from a failed stream to `converse` is the move a lane would
otherwise invent, and it is forbidden twice over: ADR-0168 §9 has the gateway "not
retry silently", and ADR-0173 §7 refuses the same fallback one layer in because
after the first chunk it "produces a complete answer that does not begin with the
text the user already read". A second attempt is the caller asking again. Here the
caller is the front end, which is ours, in this repository and inside its gate — so
the retry policy is visible, reviewable and the owner's to see, rather than a
gateway behaving as though it had answered once when it answered twice.

### 4. A delivery stream, and one delivery written to every one that is open

> **Normative.** A browser receives notifications on a **delivery stream** — one
> it established, carrying no other exchange — and on no other path.

> **Normative.** The gateway holds a `next_notification` poll against the hub
> **while and only while** at least one delivery stream is open. It opens its
> delivery connection when the first opens, polls again as each poll completes,
> and holds no poll at any other time.

> **Normative.** A delivery a poll returned is written to **every** delivery
> stream open at the moment it returned, unchanged, in the order the polls
> returned them. The gateway re-orders nothing, filters nothing, de-duplicates
> nothing, withholds nothing, and re-judges no notification the hub disposed.

> **Normative.** The gateway retains no notification. A delivery stream opened
> after a delivery was written carries no replay of it; a delivery returned while
> no stream is open is written nowhere; and the hub's durable outbox (ADR-0131 §3)
> is the only place an undelivered notification is held.

> **Normative.** The gateway writes on every open delivery stream at least once
> per `gateway_notification_budget` (§8): a delivery where the poll returned one,
> and otherwise a value carrying nothing but its own kind.

> **Normative.** A poll the gateway cannot complete ends every open delivery
> stream with a terminal value reporting it, distinguishing a transport failure
> from a request the hub received and declined (ADR-0168 §9). The gateway polls
> again only when a browser establishes a delivery stream afresh, and retries no
> poll of its own motion.

> **Normative.** The gateway holds at most one value pending per stream and
> queues nothing behind one. On a delivery stream a write that has not completed
> when the next value is due on it is abandoned and that stream is ended, so a
> browser that stops reading cannot delay another's delivery. An answer stream has
> one reader and nothing to protect from it, and the turn's own budget bounds the
> exchange.

**Polling only while somebody is listening is the clause the rest of the section
falls out of.** A poll that returns a delivery to a gateway with nowhere to put it
has taken an entry, minted a `delivery_id` and started a lease — ADR-0131 §2a
makes those one indivisible step — so the notification is then withheld from
anything else for `hub_notification_lease`, for a browser that was never there.
Polling on demand costs nothing: the outbox is durable and survives a restart, so
a notification produced while no browser is watching waits in the place ADR-0131
§3 built for exactly that, rather than in a second buffer the gateway would have
to bound, age and destroy.

**Writing to every open stream rather than to one is the fan-out, and it is the
only shape that is not a silent fault.** Choosing one stream and starving the rest
means a second tab shows nothing with nothing saying why — ADR-0083's ruling 4
failure. Evicting an incumbent stream when a new one opens is worse and the corpus
has refused it twice for the same reason: ADR-0131 §2 closes the *second* poll
because "newest poll wins" lets anything that can reach the listener evict the
owner's real notifier, and ADR-0168 §4 refuses to evict a session on the ground
that it "hands any local caller a silent lever to log the owner out". Fanning out
costs one write per open stream and has no eviction in it at all.

**And fanning out is relaying, not authoring, which is the golden-rule-3 question
this section has to answer rather than assert.** ADR-0168 §1 permits the gateway
"rendering what those calls returned" and forbids it composing behaviour the
promoted surface does not offer. Every clause above is about *when* the gateway
calls and *to how many readers it renders one answer* — it holds nothing, decides
nothing about a notification's content, and adds no state a browser could observe
that the hub did not produce. What it deliberately does not do is the thing that
would be authoring: keep a notification the hub gave it, so as to give it to
somebody else later. §12 records why ADR-0168 §1's biconditional survives this
whole.

**The keep-alive is not decoration and the exit test is why.** The exit test puts
a browser on a phone, reaching a gateway over an overlay, holding a response body
that may be silent for as long as the assistant has nothing to say. A stream that
writes nothing for an hour is a stream nothing can distinguish from one that has
died, at either end — and ADR-0168 §9 is explicit that a browser reaching a
running gateway must learn that the hub is down rather than that nothing is there.
One write per poll cycle makes the liveness of the gateway, of its hub connection
and of the browser's own socket observable at a bounded cadence, and it costs one
value and no second figure, because §8's budget is what already paces the poll.

**Abandoning a stalled delivery stream is the bound ADR-0094 §9 asks for, taken at
the only place fan-out creates one.** With several readers of one value, a reader
that stops reading applies backpressure to the writer, and a writer that waits on
it delays every other reader. Ending that stream keeps the gateway's per-stream
state at one value, keeps the delay off the other streams, and costs the abandoned
browser a reconnect — which is free, because a session outlives its connections
(ADR-0168 §8).

### 5. The acknowledgement never leaves the gateway

> **Normative.** The gateway acknowledges a delivery on its next poll, and it
> acknowledges a delivery it wrote to at least one open delivery stream and no
> other. Where no stream was open when the poll returned, it acknowledges nothing,
> and the entry returns to the outbox when its lease expires (ADR-0131 §3).

> **Normative.** A `delivery_id` never reaches a browser. It is placed in no value
> the gateway writes on a stream, in no response body, in no document and in no
> URL, and no browser request carries one. No browser acknowledges, retires,
> withdraws or dismisses a delivery.

> **Normative.** ADR-0168 §3's prohibition binds unchanged: no browser identity,
> session value or per-browser identifier crosses the wire to the hub in any frame,
> and nothing in this ADR makes the hub able to tell two browsers behind one
> gateway apart or conditions any rule on its being able to.

> **Normative.** When the last delivery stream ends, the gateway closes its
> delivery connection. Under ADR-0131 §2a that releases the device slot and the
> hub's delivery capacity in one step, and cancels an outstanding poll that has not
> yet selected an entry.

**The `delivery_id` stays inside the gateway because of what ADR-0131 §4 says it
is.** It is "a **capability**": 128 bits from a secure source joined to a
monotonic counter, and the engine "can honour it without ever knowing who is
asking", precisely so that "the entry was written to exactly one device, so
exactly one device holds the token." A value with that property, handed to a
browser, is a credential this system minted, held in a browser, spendable against
the hub. ADR-0172 §1 closes the class of such values at three and says so twice —
"admitting a fourth kind takes its own ratified decision", and no lane may "widen
this class by resemblance." Handing the token outward would be that fourth kind,
bought for nothing this milestone needs.

**Acknowledging on the write rather than on the render is where at-least-once
stops, and it is stated rather than argued away.** ADR-0131 §3's guarantee runs to
the device; past the gateway the guarantee is that the notification was written to
at least one stream, not that a person read it. A browser whose connection dies
between the write and the paint loses that notification. That is the same shape
ADR-0131 §2a already accepts one hop in — "an entry selected just as the connection
dies is leased to a device that never receives it" — reached one hop further out,
and closing it would mean a browser holding the capability above.

**The zero-stream arm costs one lease and buys the absence of a buffer.** A poll
that returns just as the last stream ends has selected an entry, so the entry is
leased and comes back after `hub_notification_lease` rather than immediately. The
alternative is for the gateway to hold it — which is the store §4 refuses. Closing
the delivery connection when the last stream ends is what shrinks that window to
the race itself: ADR-0131 §2a cancels a poll whose connection goes away before the
selection step and "takes no entry".

### 6. What a browser reaches is a closed enumeration of five operations

> **Normative.** The browser-facing surface resolves to calls on exactly these
> operations of the promoted engine surface and no others: `converse`,
> `converse_streaming` (ADR-0173 §4), `recent_conversations`, `conversation`,
> `forget_conversation`, and `next_notification` — which no browser request names,
> which no browser argument reaches, and which only §4's poll originates.

> **Normative.** Every other operation the promoted surface carries is unreached
> from a browser, and no lane may add one without its own ratified decision. In
> particular ADR-0168 §12's inheritance to milestone 15 is untouched and is not
> read as lifted by ADR-0174's deployment permission: the five connection
> operations, `resume` and `pending_confirmations`, the grant surface, the belief
> and question surfaces, and the notification review surface — `notifications`,
> `dismiss_notification`, `forget_notification`, `notification_preferences` and
> `set_notification_preferences` — are milestone 15's, and a gateway dialling its
> hub over loopback reaches none of them from a browser (ADR-0174 §11).

> **Normative.** This ADR creates no principal, no grant and no per-browser scope,
> and no operation above is conditioned on which browser asked. ADR-0099 §1's
> single principal is untouched: every browser the gateway admits is the owner, and
> a browser reaches exactly what the gateway's own device reaches and no more
> (ADR-0174 §4).

**An enumeration rather than a rule about what is forbidden, for ADR-0168 §6's
own reason.** That section made its record "an enumeration rather than an
exclusion list, because an exclusion list was wrong here", and "naming what may
appear is the only form that stays right when a later lane adds a request shape
nobody has thought of yet." The promoted surface has thirty-one operations today
and gains one with ADR-0173; a browser surface defined by what it excludes gains
every one of them silently.

**Milestone 15's inheritance is restated because ADR-0174 made it newly easy to
lose.** ADR-0168 §12 recorded that the connection operations are refused on the
hub's remote listener and refused client-side, and handed the question to
milestone 15. ADR-0174 §11 then observed that "a gateway dialling its hub over
loopback does not meet that refusal" — so the deployment ADR-0174 permits removes
the mechanical guard, and the only thing left holding the line is a clause. This is
that clause, and it holds the line for the whole surface rather than for the five
methods that happened to be guarded.

**`forget_conversation` widens what a script on the gateway's own origin can
spend, and the honest accounting is that it widens it by less than what is already
there.** ADR-0168 §6 states the residual plainly — "script running on the
gateway's own origin defeats both halves, because it need not read either; it can
simply issue requests the browser will authenticate" — and that residual has
covered `converse` since milestone 13. A turn can approve a tool, execute it and
durably commit a non-idempotent effect (ADR-0173 §9's own reasoning turns on it),
which is a strictly larger power than forgetting one conversation. So this
milestone adds a destructive operation to a surface that already carried a more
destructive one, and it adds no new class of residual. What bounds it is unchanged:
the text-not-markup clause, the content security policy, the session's ceiling and
expiry (ADR-0168 §8), and its death with the gateway process (ADR-0168 §4).

**A front-end confirmation before a forget is not a control and is not required
here.** It is defeated by the same origin-resident script the residual is about,
so requiring one would be a clause that reads as a protection and is not one. What
the front end does about it is a rendering decision the implementing lane owns, and
the CLI's own order — read the conversation, then forget it — is the pattern
available to it.

### 7. A connection carrying an open stream is not idle

> **Normative.** A connection on which a response the gateway has not finished
> writing is outstanding is **not idle**. `gateway_read_timeout` runs from the
> completion of the last **response** the connection carried, in place of the last
> complete request, and closes no connection while a stream on it is open.

> **Normative.** Every other clause of ADR-0168 §8 binds unchanged and binds on
> both listeners as ADR-0174 §8 requires — the admitted-versus-unadmitted
> partition, the close on a refusal, the one-request bound on an unadmitted
> connection, `gateway_max_browser_connections`, `gateway_max_pending_connections`
> and `gateway_max_request_bytes`, which bounds a request and not a response.

> **Normative.** A stream ends no later than the session that admitted it, and the
> gateway ends every stream a session held at the moment that session ends.

> **Normative.** An open stream is not use of the session that admitted it.
> `gateway_session_idle_timeout` is refreshed by a request the gateway admits and
> by nothing else — not by a stream's continued existence, not by a value the
> gateway writes on one, and not by a delivery poll.

> **Normative.** The gateway's delivery connection counts against
> `gateway_max_hub_connections` exactly as any hub connection does, and a browser
> request that would need one beyond that ceiling is refused naming the limit, as
> ADR-0168 §8 already requires. No lane gives delivery its own connection budget at
> the gateway, which is ADR-0131 §5's rule applied at this door.

**The first clause is a supersession and §12 carries the record, because a reader
holding only ADR-0168 §8 builds a gateway on which no stream can exist.** §8 says
the gateway "closes it `gateway_read_timeout` after the last complete request it
carried" — thirty seconds by default — and every stream this ADR defines is a
response outstanding long after its request completed. That would end a delivery
stream half a minute after it opened and would cut a turn whose composition took
longer, on a deadline whose stated purpose is to reclaim connections that are doing
nothing. PR #1331 already disclosed reading it as an idleness bound, "a wall-clock
read would kill the request the deadline protects" — this clause is that reading
made a ruling and extended to the case a streamed response creates, which the
shipped reading does not reach: a stream between two writes is idle in the read
direction and is not idle in any sense the deadline was written about.

**Keying it on the response rather than exempting streams is deliberate.** An
exemption would need a list of which requests are exempt, which is the partial
enumeration ADR-0168 §1's biconditional and §6's collapse key were each rewritten
to remove. "A response the gateway has not finished writing" is a property every
connection is on one side of at every moment, so no request shape can be added
later that the rule has no opinion about.

**Not refreshing the idle timeout is the clause that keeps ADR-0168 §4's bound
from going the way of `gateway_max_sessions`.** #1320 records a figure that is
live in the code and unreachable in practice; a session that a held-open stream
kept alive would make the idle bound the second one. The bound exists so that an
unattended session dies, and a page left open is exactly the unattended case, so a
stream must not be the thing that argues the owner is present. The cost is real and
is disclosed in Consequences: a browser doing nothing but watching for
notifications loses its session after `gateway_session_idle_timeout`, and under
ADR-0168 §5's one mint per process that means restarting the gateway. That is the
cost ADR-0168's own Consequences already state, arriving in a new place, and
milestone 16 is where §5 is revisited (ADR-0174 §9).

**The hub-connection clause is arithmetic worth stating because it silently
changes.** ADR-0168 §8 set `gateway_max_hub_connections` at 8 so that a gateway
cannot consume the whole of `hub_max_connections` and leave the owner's CLI reading
an unattributable refusal. A gateway serving a delivery stream now holds one of
those eight permanently, leaving seven for turns. No figure moves — ADR-0174 §8
already makes these the gateway's totals rather than each listener's, and the
reasoning behind the number is untouched — but a lane and an owner should both know
that the ceiling is one smaller in practice than it reads, and that a gateway
configured with a ceiling of one can serve a delivery stream or a turn and not
both, refusing the other with a message naming the limit.

### 8. The figure

Named here rather than left to the implementation, on ADR-0168 §8's ground, taken
from ADR-0084 §3 and ADR-0083 §7: "a 'bounded default' with no figure is two
conforming stores handing the same continuation different history."

| `Settings` field | Type | Default |
| --- | --- | --- |
| `gateway_notification_budget` | `timedelta` | 20 s |

> **Normative.** It is refused at settings load unless it is strictly positive, in
> the `gt=timedelta(0)` form ADR-0083 §7 adopted and ADR-0168 §8 applied. It is not
> nullable and takes no value meaning "off", exactly as ADR-0168 §8's ten do.

> **Normative.** It is the value the gateway supplies as `next_notification`'s
> `budget` argument (ADR-0131 §4), and it is the interval within which §4 obliges a
> write on every open delivery stream. One figure paces both, because the write a
> browser observes is the completion of the poll the budget bounds.

> **Normative.** No load-time check relates it to `hub_max_notification_budget`,
> which is another process's setting and may be another machine's. A budget the hub
> declines is a request the hub received and declined, reported under ADR-0168 §9
> as distinguishable from a transport failure, and the gateway does not retry it
> (§4).

**Twenty seconds, and where the number comes from.** It is not a latency budget —
`next_notification` returns the moment the hub has something, so the figure decides
only how long an empty poll waits before it is renewed, and therefore how often the
browser learns that everything is still alive. Twenty seconds is short enough to
keep a phone's connection observably live across an overlay and to make a dead
gateway legible within one cadence, and long enough that a poll cycle costs one
frame pair rather than being a spin. It costs the hub nothing measurable, because
ADR-0131 §2a holds the delivery connection across polls — "a later
`next_notification` on that same connection uses the claims it already holds and
makes no new ones" — so there is no handshake and no slot churn between cycles.

**It is deliberately far below the hub's own ceiling, and the cross-process
refusal is why.** `hub_max_notification_budget` defaults to 300 s and the hub
**refuses** a budget above it rather than clamping one. Two processes, possibly two
machines, so neither `Settings` can validate against the other; a default an order
of magnitude below the hub's leaves an owner who tunes one figure a wide margin
before they meet the other. What happens if they do meet it is legible rather than
silent — a declined request, reported as one — and that legibility is what makes a
load-time check unnecessary rather than merely impossible.

**One figure and not two, because the second would be a second claim about the
same fact.** A separate heartbeat interval would be a number that can disagree with
the poll cadence, and the two disagreeing has no defensible interpretation: a
heartbeat shorter than the poll obliges a write with nothing to write about, and one
longer is inert. That is ADR-0084 §3's argument against a second length member,
applied to a clock.

### 9. Rendering

> **Normative.** The front end inserts every value the hub returned into the page
> as text through the document's own text node, never as markup and never through
> any interface that parses markup (ADR-0168 §6). A renderer that does so satisfies
> ADR-0173 §10's boundary clause by construction, because a text node interprets
> nothing; a front end that ever renders a value by markup owes §10's rule that
> neutralisation is applied to accumulated text and never independently to each
> chunk.

> **Normative.** A notification is rendered inside the open page and by no other
> means. This ADR authorises no Notification API, no Push API, no service worker,
> and no operating-system notification, and ADR-0174 §7's stop condition stands for
> any browser capability available only in a secure context.

> **Normative.** A notification's content is engine-supplied text and is
> neutralised exactly as a reply is, and no clause of this ADR permits a
> notification to be rendered with a warrant it does not carry — ADR-0099 §4's floor
> and ADR-0073 §4's before it bind a notification's summary and detail as they bind
> a belief's rendering.

**ADR-0173 §10's boundary clause is the one most likely to be reintroduced as a
bug, and it is worth saying exactly why this front end is not exposed to it.** §10's
attack is against a renderer that *escapes* markup: an adapter neutralising `[/dim`
and `]` in separate chunks produces nothing either call would refuse and emits live
markup when the two are joined, so "the attribution and the escaping must derive
from data the renderer holds, never from where an untrusted producer chose to break
the text." A DOM text node has no escaping step to split — appending two text nodes
produces two text nodes — so a `textContent` renderer is immune structurally rather
than by care. That is the property the second half of the clause protects: the
immunity belongs to the *mechanism*, and a front end that adopts a markup-rendering
one loses it and inherits §10's obligation whole.

**The in-page clause records the owner's ruling rather than deciding it.** ADR-0174
§7 made a secure-context requirement a stop condition on this lane and named the
capabilities that need one; the owner ruled on #1230 on 2026-08-21 that the exit
test's pushed notification is in-page. That is the reading ADR-0174 §7 itself
identified as needing no secure context — "a notification rendered in the open page,
driven by the delivery connection ADR-0131 §2 holds, needs no secure context and is
what this decision supports."

### 10. What this decides no part of

> **Normative.** This ADR decides no `core/protocols.py` and no `core/types.py`
> surface. A lane implementing it that finds it needs either stops and owes its own
> contract ADR, merged first (golden rule 5, ADR-0015 §5).

> **Normative.** It changes no member of the connect exchange, no frame's encoding,
> and no method's arguments or results, so no lane implementing it changes
> `PROTOCOL_VERSION` for it (ADR-0124 §9). Every wire-visible change milestone 14
> needs is ADR-0173's, and the bump it obliges is that ADR's lane's.

> **Normative.** It adds no clause to ADR-0131, ADR-0172 or ADR-0174, reopens no
> ruling of any of them, and decides nothing ADR-0168 defers that is not named in
> this section.

**Deferred, by name, each with the condition that fires it:**

- **A stream from the browser to the gateway** — a request whose *body* streams,
  which is what microphone capture would need (#1318, `track:voice`'s first rung).
  §1 supplies a carrier in one direction only. It is gated twice over: ADR-0174 §7
  already stops a lane needing a secure-context capability, and microphone capture is
  one; and a socket, which is the obvious carrier for it, cannot present ADR-0168
  §6's header half. Whoever takes it owes a decision on both, and this ADR forecloses
  neither.
- **A transport-layer security arrangement for the remote browser listener, and
  every capability that needs one** — an operating-system notification, the
  Notification and Push APIs, a service worker, `crypto.subtle`. ADR-0174 §7 and §11
  hold the question with its trigger, and the owner's in-page ruling is what makes
  milestone 14 reachable without it, not a decision that it is never needed.
- **The notification review surface** — `notifications`, `dismiss_notification`,
  `forget_notification` and the two preference operations. Milestone 15's control
  surfaces. Dismissal in particular is a judgement about the notification *record*
  (ADR-0130), which is a different act from the delivery acknowledgement §5 keeps
  inside the gateway, and conflating them is the mistake this deferral exists to
  prevent.
- **`resume`, `pending_confirmations` and the CONFIRM prompt.** Milestone 15 names
  them. A browser turn that parks is rendered as a park and the owner resumes it at a
  terminal, which is what the shipped front end already tells them.
- **Multiplexing.** The other half of ADR-0084 §3's reserved second job stays
  reserved and unspent at both edges; §1 keeps one exchange per stream.
- **Resuming an interrupted stream.** ADR-0173 §13 declines it and names its
  condition (#1314); a browser whose stream is cut re-asks, and ADR-0173 §9's
  behaviour is what it inherits.
- **A second live session, a durable session, and several browsers admitted at
  once.** ADR-0168 §5 and §12 defer them to milestone 16, ADR-0172 §2's replacement
  (d) makes the process-lifetime bound a condition of three ADR-0004 exemptions, and
  ADR-0174 §9 rules that milestone 14 is not that revisit. #1320 and #1329 hold until
  then, and §7's idle-timeout clause adds one more symptom to the case rather than
  reopening it.
- **The framing, the media types and the paths** (§2), which are the implementing
  lane's on ADR-0168 §12's own division.
- **Whether the gateway should hold a poll while a session is live and no stream is
  open.** §4 rules it does not, on the lease argument; a lane that measures a real
  cost in first-notification latency may buy the alternative then, and it would owe an
  argument about where the delivery goes.
- **A second gateway on one device.** ADR-0168 §12 leaves it open, and §4 above
  makes one consequence concrete rather than deciding it: on the loopback listener
  every peer is the single device identity `None`, so two gateways on one machine
  contend for one delivery slot, and the second's poll is closed under ADR-0131 §2.

### 11. What milestone 14 tells #975, which asked to be told here

#975 asks whether the delivery seam's complete contract should be ratified into
`core`, superseding ADR-0131 §3b's one-method `NotificationOutbox`, and #1230
parks it with "milestone 14 will tell". This is that milestone's decision, so it
answers rather than re-parks.

**It tells one thing, and the thing it tells is negative.** The first real
consumer of the delivery seam is this surface, and it reaches the seam entirely
through `AssistantEngine.next_notification` — one promoted method, already in
`core/protocols.py`, ratified by ADR-0131 §4. It never holds a `NotificationOutbox`,
never sees `DeliveryOutbox`'s select-and-lease, acknowledge, withdraw, reconcile or
recover-leases, and could not: it is a spoke on the far side of the wire, and
ADR-0168 §1 forbids it opening a store. So the first push consumer supplies **no
evidence** that the complete outbox surface is a contract between subsystems, and
the question rests exactly where #975 left it — on the `orchestration`-internal
argument, weighed against the `wire.server.Admission` and `service.scheduler`
precedents that a listener's own collaborator is not one.

> **Normative.** This ADR neither promotes nor declines to promote the delivery
> outbox surface, and no lane cites it toward either. What it records is that
> milestone 14's consumer is on the far side of the promoted surface and therefore
> supplies no input to that question, so #975 stays open on its own terms and is not
> discharged by this milestone's arrival.

That is worth a section rather than a line, because a parked question whose
named trigger fires and produces nothing is otherwise read, later, as a question
that was answered.

### 12. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

**One clause is superseded and this change writes the record** — ADR-0168's
`Status` line and an appended dated note, in the scope §7 names.

- **ADR-0168 §8's read-deadline sentence**, "The gateway closes it
  `gateway_read_timeout` after the last complete request it carried", **only as it
  reaches a connection carrying a response the gateway has not finished writing.** A
  reader holding only §8 ends every stream §1 defines thirty seconds after its
  request arrived, which is not a stricter reading of the surface — it is a gateway
  on which the surface cannot exist. ADR-0070 §1's first limb, and the replacement is
  §7's response-keyed deadline. Every other sentence of §8 stands, on both listeners
  (ADR-0174 §8).

**No record is owed on:**

- **ADR-0168 §1's biconditional**, examined at length because it is the clause the
  fan-out most looks like it falsifies. §1 says a browser request reaches the
  promoted surface iff it is admitted and asks the assistant for something, "and
  every request meeting both resolves to calls on that surface and to rendering what
  those calls returned." A delivery stream is admitted and asks the assistant for
  something, and it is answered from calls on that surface and from nothing else —
  the gateway holds no notification of its own (§4), so every value it writes is one
  `next_notification` returned. What a second delivery stream does not do is
  *originate* a further call, because ADR-0131 §2 gives the device one slot; and §1's
  sentence makes no cardinality claim, requiring that a request resolve to calls on
  that surface rather than to a call of its own. The clause's stated purpose — that
  golden rule 3 be "checkable rather than aspirational", so that a gateway which
  authored anything is in breach detectably — survives whole, which is the test
  ADR-0070 §1 sets and which ADR-0173 §6 applied in the same form. **The alternative
  reading is named rather than hidden**: a reader taking "resolves to calls" as
  "originates a call" would build one poll per stream, and would be closed by
  ADR-0131 §2 on the second — so the reading that is wrong is the one the corpus
  already refuses mechanically, and the two readings do not produce two conforming
  gateways.
- **ADR-0168 §6's four request classes.** Untouched, and this ADR adds no fifth. A
  streamed turn and a delivery stream both "ask the assistant for something" and are
  `assistant-request`; the assets, the bootstrap exchange and the residual fourth
  class are unchanged. §6's enumeration of permitted Tier 2 facts on a record is
  likewise untouched — this ADR adds no field to it, and ADR-0174 §3's one addition
  stands as that ADR wrote it.
- **ADR-0168 §5, §4 and §3.** Used as given. One bootstrap value, one session per
  process, the ceiling that refuses rather than evicts, the two-value admission and
  the two pre-session exceptions all bind unchanged; §7's idle-timeout clause applies
  §4's bound rather than narrowing it, and §10's deferral leaves §5 to milestone 16.
- **ADR-0168 §9.** Used as given and relied on three times — §3's no-substitution
  clause, §4's poll-failure clause and §2's terminal-value clause are each ruling 4's
  legibility carried to a new value on a stream. Nothing about it is read more widely.
- **ADR-0168 §12.** Three of its deferrals are discharged by the decision that named
  them, which is ADR-0083 §15's stacked addition on its own test: the browser-facing
  surface and its push carrier, the fan-out, and — jointly with ADR-0174 §11 — the
  streaming carrier. A deferral discharged by the milestone it names is not an
  amendment of the text that deferred it. §12's fourth and fifth deferrals, milestone
  15's connection operations and milestone 16's durable session, are restated as
  standing rather than touched.
- **ADR-0131 §§1, 2, 2a, 3, 4, 5.** Used as given, every one. §1's prohibition on
  an unsolicited frame is untouched, because the gateway asks; §2's one slot per
  device is what §4 is shaped around; §2a's claim-and-release is what §5's
  close-the-connection clause invokes; §3's outbox is relied on as the only buffer;
  §4's `delivery_id` is treated as the capability that section says it is; and §5's
  refusal to give delivery its own budget is applied at a second door.
- **ADR-0173 §§1–4, 9, 10, 12.** Used as given. §12 hands this decision the carrier
  choice in terms — "chunked transfer on the request the browser made, an event
  stream on a request it made, or a socket it opened are all consistent with the
  clause above; choosing among them is milestone 14's" — and §1 above chooses the
  first and refuses the third on ADR-0168 §6's ground rather than on any clause of
  ADR-0173. §3's authority structure is preserved rather than eroded; §9's cut-stream
  behaviour is what a browser inherits; §10 binds the front end as an adapter and §9
  above says so. §12's observation that a gateway can carry every frame ADR-0173
  defines without a server-initiated browser message stays true, and is what §1's
  one-direction carrier demonstrates.
- **ADR-0174 §§1, 4, 7, 8, 10, 11.** Used as given. §1's fourth boundary is what a
  stream crosses when the browser is on another device, and nothing here adds a
  boundary or a recipient — the set of browsers is unchanged, since §4's admission and
  the owner's device list decide it and no clause of this ADR touches either. §7's
  stop condition is discharged by the owner's ruling, on the reading §7 itself names.
  §8's shared ceilings are applied at §7. §10's direction rule is implemented rather
  than amended. §11's deferral of the streaming carrier is discharged by the milestone
  it names, and its warning that a loopback-dialling gateway does not meet milestone
  15's refusal is what §6's enumeration answers.
- **ADR-0172.** Untouched, and §5 is careful about the one place it could have been
  widened: §1's class of three is closed, a `delivery_id` is not admitted to it, and
  the reason a browser does not hold one is that admitting a fourth kind "takes its own
  ratified decision". No exemption is read more widely and no new Tier 0 value is put
  in a browser.
- **ADR-0094 §2 and ADR-0124 §10.** Satisfied without extension. Every stream is
  established by the browser and written on only in answer to what the browser asked
  for; the hub still never dials a spoke and the gateway never dials a browser.
- **ADR-0084 §3.** Its serial rule, its mismatch rule and its permanent framing
  freeze are untouched — this ADR changes nothing on the wire — and its reserved
  correlation id is spent no further here than ADR-0173 spent it. §1's refusal of
  multiplexing at the browser edge is that reservation respected rather than read
  more widely.
- **ADR-0099 §1 and §4.** §1 is used as given: one principal, and §6 states in terms
  that no per-browser scope is created. §4's rendering floor is applied to a
  notification's content at §9, which is the floor being obeyed rather than extended.
- **ADR-0130.** Unreached. This ADR reads no notification's summary, detail,
  confidence, sensitivity or references, and re-judges no disposition; what it moves
  is a `NotificationDelivery` the hub already disposed.
- **ADR-0054.** Applied. One `Settings` field is contract surface in its sense and
  not `core` Protocol or type surface, which is the position ADR-0168 §8 and ADR-0174
  §8 were both in.
- **Golden rule 3.** §1's refusal of multiplexing, §4's refusal to retain a
  notification and §6's closed enumeration are each the rule applied. A gateway that
  buffered, correlated or filtered would be authoring, and each clause is what makes
  that detectable.

## Consequences

- **The browser stops waiting for a whole answer.** A turn that plans, retrieves,
  executes a step and then composes shows its answer as it is written rather than
  after it, which is the product milestone 18 built the hub half of and the reason
  this milestone consumes it.
- **The delivery seam gains its first consumer.** `next_notification` has been
  fully built, wired and exercised only by tests since ADR-0131 merged; a browser
  holding a delivery stream is the first thing in this system that reads it, and the
  outbox stops being a queue nothing drains.
- **The gateway holds one hub connection permanently while anyone is watching**,
  so `gateway_max_hub_connections` is one smaller for turns than it reads. No figure
  moves and the arithmetic is stated (§7) rather than discovered.
- **`interfaces/gateway/http.py` grows a second response shape**, which is the
  largest single piece of work this decision creates: `Response.body` is `bytes` today
  and every response carries a `Content-Length`. It is confined to one module and it
  is far smaller than the framing a socket would need.
- **A browser that only watches loses its session in an hour.** §7 refuses to let a
  held-open stream refresh `gateway_session_idle_timeout`, so a page doing nothing but
  waiting for a notification expires on the idle bound — and under ADR-0168 §5's one
  mint per process, recovering costs a gateway restart. That is the price of keeping
  the idle bound from going the way `gateway_max_sessions` already has (#1320), it is
  paid visibly, and milestone 16 is where it is revisited.
- **At-least-once ends at the gateway.** The hub guarantees delivery to a device;
  past that, the guarantee is that the notification was written to at least one open
  stream. A browser whose connection dies between the write and the paint loses it
  (§5). Closing that would mean handing a browser the `delivery_id` capability, which
  ADR-0172 §1 closes its class against.
- **The surface a browser reaches is now a list rather than an accident**, and
  adding to it costs a ratified decision (§6). That is what keeps ADR-0174's
  permission to run a gateway on the hub's own machine from quietly handing a browser
  the five connection operations milestone 15 owns.
- **What becomes harder:** every later browser-facing capability that wants a
  socket now argues against ADR-0168 §6 rather than against a preference. That is the
  intended shape — the argument is available, it is a real supersession with a real
  cost, and voice's first rung is the case most likely to make it (§10).
- **Revisit when** a browser needs to stream *to* the gateway (§10); when a
  secure-context capability is required, which is ADR-0174 §7's own trigger; when
  milestone 16's durable session admits a second browser, which turns §4's fan-out
  from one browser's tabs into several browsers and makes the abandonment clause load
  bearing; or when a measured first-notification latency makes polling on demand
  (§4) worth trading for a poll held while a session is live.

## Alternatives considered

- **A WebSocket, carrying everything.** The shape most people would build, and the
  one #1230's own milestone-13 text anticipated ("exposes WebSocket/HTTP to the
  browser"). *Rejected in §1, on a mechanical fact rather than a preference:* a page
  cannot set a request header on the opening handshake, so ADR-0168 §6's header half
  has nowhere to travel that §6 admits, and a request carrying the cookie half alone
  is one §6 refuses. Beyond that it would oblige the gateway to invent correlation at
  the browser edge — the multiplexing ADR-0084 §3 deferred and ADR-0173 §1 declines to
  add — or to be used serially, in which case it buys nothing a response body does not.
- **Server-sent events through `EventSource`.** The native push carrier, with
  automatic reconnection and a `Last-Event-ID` resumption story already built.
  *Rejected in §1* for the same reason and with less room to argue: the constructor
  takes a URL and one boolean and there is no interface for a request header at all.
  Its own framing remains available to the implementing lane as a way to *frame*
  values on a stream a `fetch` reads, which is what §2 leaves open; what is refused is
  the browser interface, not the format.
- **A one-time ticket in the stream's URL, so a socket or an `EventSource` could
  authenticate.** The workaround that makes either of the two above viable.
  *Rejected.* A ticket is a value this system mints that admits a browser request,
  which is the web-session credential class in everything but name — and ADR-0172 §1
  closes that class at three and forbids widening it "by resemblance". It would also
  put a credential in a URL, which ADR-0168 §5 and §6 each forbid in terms.
- **A gateway-side notification buffer, so a browser opening a stream sees what it
  missed.** Friendlier, and it would close §5's last-hop gap. *Rejected in §4.* It is
  the durable outbox ADR-0131 §3 already built, rebuilt one hop out with none of its
  bounds — and ADR-0094 §9 permits edge state only where it is bounded in size and in
  age and destroyed continuously. The outbox already survives a restart and already
  holds what nobody has heard; a second copy in a process whose whole state dies with
  it is strictly worse.
- **Poll the hub whenever a session is live, rather than while a stream is open.**
  It would cut first-notification latency to nothing. *Rejected in §4*: a poll that
  returns to a gateway with nowhere to put the answer has selected an entry, minted a
  `delivery_id` and started a lease in one indivisible step (ADR-0131 §2a), so the
  notification is withheld from anything else for `hub_notification_lease` on behalf
  of a browser that was never there. §10 leaves it available to a lane that measures a
  real cost and can say where the delivery goes.
- **Give the browser the `delivery_id` and let it acknowledge.** It would carry
  at-least-once all the way to the page. *Rejected in §5*: ADR-0131 §4 makes that
  value a capability held by exactly one device precisely so the engine can honour it
  without knowing who is asking, and putting it in a browser makes it a fourth member
  of the class ADR-0172 §1 closes. It would also need a rule for which of several
  browsers may spend it, which is a per-browser identity the hub is forbidden to have.
- **Choose one delivery stream and starve the rest, or evict an incumbent when a
  new stream opens.** Either removes the fan-out question. *Rejected in §4*: the first
  is a second tab showing nothing with nothing saying why, and the second is the
  silent-eviction lever ADR-0131 §2 and ADR-0168 §4 have each refused, one for a poll
  and one for a session.
- **A fifth request class for a delivery stream.** It would let a record name the
  stream specifically. *Rejected in §12*: a delivery stream asks the assistant for
  something and is `assistant-request` under ADR-0168 §6's own words, so a fifth value
  would supersede an enumeration that says every request is "of exactly one class, out
  of four" while buying no rule the four cannot carry.
- **Serve only the streaming turn entry and drop `converse` from the browser
  surface.** One shape instead of two. *Rejected in §3*: ADR-0173 §5 makes a provider
  that cannot stream a runtime `ModelError` degrading to no answer at all, so a
  browser with only the streaming entry would answer nothing on a build where the CLI
  answers normally.
- **Let the gateway fall back to `converse` when a stream fails.** Free resilience,
  apparently. *Rejected in §3* on two ratified grounds at once: ADR-0168 §9 forbids
  the gateway retrying silently, and ADR-0173 §7 refuses the same fallback one layer
  in because past the first chunk it produces an answer that does not begin with the
  text the user has already read.
- **Exempt streams from `gateway_read_timeout` by naming the request shapes that
  are exempt.** Narrower than §7's supersession. *Rejected in §7*: it is a partial
  enumeration, which is the defect ADR-0168 §1's biconditional and §6's collapse key
  were each rewritten to remove — a shape added later has no clause with an opinion
  about it. Keying the deadline on whether a response is outstanding puts every
  connection on one side of the rule at every moment.
- **A second figure for the browser-facing keep-alive, separate from the poll
  budget.** *Rejected in §8*: two numbers about one cadence can disagree, and neither
  disagreement has a defensible reading — shorter than the poll obliges a write with
  nothing to write about, longer is inert. That is ADR-0084 §3's argument against a
  second length member, applied to a clock.
