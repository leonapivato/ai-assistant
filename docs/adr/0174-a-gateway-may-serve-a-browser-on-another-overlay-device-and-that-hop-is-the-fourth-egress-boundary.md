# 174. A gateway may serve a browser on another overlay device, and that hop is the fourth egress boundary

- Status: Accepted
- Date: 2026-08-21
- Note: 2026-08-23 — **the revisit §9 said this was not has landed, and it chose
  process-bound.** §9 ruled "this is not ADR-0168 §5's revisit… Milestone 16 is,
  on ADR-0168 §12's own trigger, and both issues hold together until then", and
  §11's fifth deferral held a second live session, a durable session and a durable
  browser credential to the same milestone. ADR-0182 (`track:web-client` milestone
  16, #1230, #1429) is that decision.

  **What it chose.** A gateway mints a further bootstrap value whenever the owner
  performs a mint act at the machine that runs it — the delivery of `SIGUSR1`, so
  the act is not a request and is reachable from neither listener — and at most one
  unexchanged value stands at a time. An unexchanged value gains a clock,
  `gateway_bootstrap_ttl`, defaulting to ten minutes and running from the mint, so
  **#1329 is answered**. `gateway_max_sessions` becomes reachable and refuses at two
  doors, so **#1320 is answered**; both close with that decision's implementing lane.
  A session's power still ends with the gateway process, so the durable session is
  **refused** rather than granted, and ADR-0172 §2's replacement (d) — the condition
  three ADR-0004 exemptions hang on — is kept.

  **This note changes no decision of this ADR, which is why it is a note and not a
  supersession** (ADR-0070 §1). Every clause of §9 stays true of ADR-0174: it did not
  relax ADR-0168 §5, it authorised no second bootstrap value and no durable session,
  and it left #1320 and #1329 open. §9's second clause — that ADR-0172 §2's
  replacement (d) is satisfied unchanged here — is likewise still true, and ADR-0182
  §5 keeps it true one milestone further on. What has moved is the world §9 pointed
  at, and a reader arriving at §9 is entitled to learn that the revisit landed and
  what it chose.

  **Two other things ADR-0182 leaves exactly as this ADR wrote them.** §7's held
  secure context keeps its trigger untouched — nothing in milestone 16 needs one,
  and #1230's far-future public door is neither designed for nor foreclosed. And
  §8's rule that the gateway's ceilings are the gateway's, not each listener's, is
  the clause ADR-0182 §4 makes reachable: a session minted through either listener
  counts against the same `gateway_max_sessions`, taken exactly as written.

  **One paragraph of §9 is overtaken and it binds nothing.** Its prose that a figure
  for the unexchanged value "would be an eleventh `Settings` field and a change to
  ADR-0168 §8's table and to its Consequences' field count" is unmarked text in a
  marked ADR, so it supplies no obligation (ADR-0089 §3). ADR-0182 §9 applies
  ADR-0070 §1's test to §8's table and finds no record owed — the table is not an
  exclusive enumeration — and follows the corpus's own practice: §8 of this ADR added
  three gateway `Settings` fields and ADR-0175 §8 added one, and neither wrote a
  record there. The ordinal was already overtaken by this ADR's own three when it was
  written.


- **This is `track:web-client` milestone 14's boundary decision** (#1230). Its
  exit test is *a conversation and a pushed notification, end to end, on a
  phone*, and a phone cannot host a gateway — so the arrangement ADR-0168 §2
  ruled for milestone 13, one gateway serving the browsers on its own device
  over loopback, has no subject on it. ADR-0168 §2's third clause sends that
  case here by name: "A gateway serving a browser on a device that cannot itself
  run a gateway is deferred, not decided. It requires a fourth egress boundary
  and therefore its own ratified decision superseding ADR-0124 §1's enumeration,
  and no lane may read this ADR as having granted, prepared or pre-authorised
  it." This is that decision.
- **No implementation lands with it.** No `src/`, no `tests/`.
- **It decides no `core/protocols.py` and no `core/types.py` surface** (§11), so
  golden rule 5 is not triggered. It adds three `Settings` fields (§8), which are
  contract surface in ADR-0054's sense — the position ADR-0084 §3 was in for its
  four transport figures and ADR-0168 §8 for its ten.
- **It partially supersedes two ADRs, and both records land in this change**
  (ADR-0070 §1, ADR-0082 §1, ADR-0083 §15): **ADR-0124 §1's rule as an
  enumeration**, which authorises three boundaries and calls every other egress a
  bug, and **four clauses of ADR-0168** — §2's loopback-only bind clause, §2's
  one-gateway-one-device clause, §4's sole-admitter clause and §6's exclusive
  record enumeration — each only as it reaches a separately configured remote
  browser listener. §12 applies ADR-0070 §1's test clause by clause to every other
  ADR a reader might expect this to falsify and finds no further record owed.
- **Two of those four were classified as no-record-owed in an earlier draft, and
  architecture review was right to refuse the classification.** That draft called
  §4's second admission fact and §6's added record field "additions rather than
  relaxations". An exclusive enumeration that gains a member is **false**, not
  widened, and a reader building session-only admission out of §4 now builds the
  wrong door — ADR-0070 §1's first limb, twice. ADR-0017 §5 refuses "a narrowing
  of a ratified clause presented as a clarification"; the earlier draft was doing
  that in the other direction, and §12 now carries the record instead.
- **Its required review set is adversarial *and* architecture.** It fixes an
  egress boundary and an admission rule, which is the pair ADR-0124 took both
  lenses for, and `CONTRIBUTING.md` makes a change contract-surface when it is
  the ADR deciding that surface.
- **One consequence is named up front because it can move a milestone.** A
  browser reaching a plain-HTTP page on an overlay address is **not in a secure
  context**, and several browser capabilities a chat surface reaches for — the
  Notification and Push APIs, service workers, `crypto.subtle`, microphone
  capture — are gated on one. §7 rules the scheme, states the cost, and makes
  the requirement a **stop condition** on the milestone-14 surface lane rather
  than something it discovers with code written.

## Context

### What milestone 14 asks for, and the clause that sends it here

ADR-0168 put the browser behind a **gateway**: an ordinary spoke of the client
profile that enrols as a device under ADR-0124 §6, reaches the hub over
ADR-0084's framed wire, and binds a **loopback TCP** listener for browsers on
its own machine. Milestone 13's exit test — an `ask` round-tripping from a
browser on another Tailscale device — was met by putting the gateway *on* that
device: the browser↔gateway hop never left it, and the gateway↔hub hop was
ADR-0124 §1's third boundary, already authorised.

That arithmetic is ADR-0168 §2's, and it is stated there with its own limit. The
second placement — the gateway on the hub's machine, serving a browser over the
overlay — "moves user data off H, and it is not the hub's remote transport — so
under ADR-0124 §1 as it stands, 'every other egress is a bug'. Authorising it
means a **fourth egress boundary**, superseding a normative enumeration in a
ratified ADR." §2 declined to buy that for milestone 13 because the already-ratified
arrangement satisfied the same test, and named the condition that would fire it:
"a browsing device that cannot host a Python process — a phone, which is what
milestone 14's exit test names."

The condition has fired. A phone runs a Tailscale client and a browser and
nothing of ours; there is no placement of a gateway that keeps the browser hop
inside one device.

### What the tree holds, checked rather than remembered

- **The gateway exists and is loopback by construction.**
  `src/ai_assistant/interfaces/gateway/server.py` holds `_LOOPBACK` as a module
  constant rather than a setting — "so there is no configuration that could have
  it bind a wildcard, an interface or an overlay" — and builds its authority as
  `f"{_LOOPBACK}:{settings.gateway_port}"`. `_check_door` refuses any request
  whose `Host` header is not that one string.
- **The surface is HTTP and there is no WebSocket.** ADR-0168 §12 declined a
  bidirectional carrier for milestone 13 on the ground that nothing emitted a
  server-initiated message; the implementation shipped four request classes —
  an asset, the bootstrap exchange, an assistant request, and everything else.
- **The overlay agent already answers "who is this peer".**
  `src/ai_assistant/service/overlay.py` calls `/localapi/v0/whois?addr=…` on the
  agent's Unix socket and returns the peer's stable node identifier; the socket
  itself is held to `wire/overlay.py`'s custody conditions
  (`check_agent_peer`, `check_configured_socket`). This is the mechanism
  ADR-0124 §4 ratified for the hub's remote listener, and it is a call to a
  daemon on the same machine over a local interface — the class ADR-0084 §1
  already reasoned about, which "engages neither clause".
- **`core/config.py` already carries the shape a second overlay listener wants.**
  `hub_remote_address` is `str | None`, unset meaning the listener is off, and
  its validator refuses five things in a named order — a wildcard, a loopback
  address, a multicast address, a link-local address, and an address reachable
  from the public internet — with the reason each fails. `client_overlay_agent_socket`
  names the agent on *this* machine and is documented as "Ignored when
  `remote_hub_address` is unset".
- **The ten `gateway_*` figures are stated over the gateway, not over a
  listener.** `gateway_max_browser_connections` bounds "connections of both kinds
  together"; `gateway_max_hub_connections` bounds what the gateway holds to the
  hub. None of them is written per-listener, because until now there was one.
- **The client refuses a name for the hub's address, deliberately** (#912).
  `wire.address.check_remote_address` admits a literal IP only, so a MagicDNS
  name is refused with a message naming the setting. That posture is about a
  *destination* and §6 below is careful not to read it as covering a `Host`
  header.

### Why the third boundary does not stretch to cover this

The tempting economy is to say the browser leg is already inside ADR-0124 §1 —
it is the same overlay, the same two machines, the same owner. It is not, and the
reason is not formalism.

ADR-0124 §1 names its boundary as "the hub's **remote transport** between the hub
and a device the owner has enrolled — its two halves being the hub's remote
listener and the client that connects to it". Everything that makes that boundary
*accountable* in ADR-0017 §4's sense hangs off those two nouns: §6's enrolment at
the hub mints the credential, §7's two-fact rule admits on it, §8's revocation
acts on the enrolment record, and §4's mutual identity check is between a hub and
a client this repository ships. A browser has none of them — ADR-0168's Context
says so in terms: "A browser cannot be enrolled under ADR-0124 §6… Nothing about
ADR-0124's two-fact rule has a subject inside a browser tab."

So reading the browser leg into the third boundary would not save a supersession;
it would import an admission rule with nothing to admit, and leave the actual
control — ADR-0168 §4's web session — outside the boundary that is supposed to
account for the transmission. A fourth boundary with its own admission rule is
the honest instrument, and it is the one ADR-0168 §2 named.

### What a browser on an overlay can and cannot supply

The loopback gateway had **neither** of ADR-0124 §7's two facts available at its
door: no `0600` bit, no overlay identity, nothing but a session it minted itself.
That is why ADR-0168 §3 had to argue the session as the whole of the control.

A browser on an overlay device is a better-placed caller than that, and it is
worth being exact about which half improves.

- **The transport-attested identity becomes available.** The connection arrives
  from an overlay address, and the gateway's own local agent will say which node
  holds it — the same `whois` call the hub already makes, over the same local
  socket, taken from nothing the peer asserts. ADR-0124 §4's obligation therefore
  has a subject here, where it had none on loopback.
- **The owner-minted credential does not change.** A browser still has no
  keyring, no `SecretStore` and no enrolment; the credential it presents is still
  ADR-0168 §4's web session, minted at the gateway from ADR-0168 §5's
  single-use bootstrap value. Nothing about that machinery is improved by the
  browser being remote, and §5 below is where each of ADR-0168 §6's arguments for
  it is re-tested against a listener that is not loopback.
- **What gets worse is the population and the scheme.** The port is now reachable
  by every device on the overlay rather than by every process on one machine —
  a different set, not a smaller one in every respect — and a page served over
  plain HTTP from an overlay address is not a secure context, which loopback
  silently was.

## Decision

We will authorise a **fourth egress boundary** — the gateway's **remote browser
listener** and the front-end bundle this repository ships, in both directions —
under ADR-0124 §2's transport posture taken whole, admitted on **two independent
facts** in the shape ADR-0124 §7 already established, with ADR-0168's session
machinery carried over unchanged except where a listener that is not loopback
falsifies the argument for it.

### 1. The rule: a fourth egress boundary, and it is the browser leg in both directions

> **Normative.** User data may leave the device only from `models/`, from the
> designated integration seam inside `tools/`, across the hub's **remote
> transport** between the hub and a device the owner has enrolled under ADR-0124
> §6, or across the gateway's **remote browser transport** between a gateway and
> a browser on another device of the owner's overlay — its two halves being the
> gateway's remote browser listener and the front-end bundle this repository
> serves to that browser; every other egress is a bug.

**Both halves are named for ADR-0124 §1's reason, and the second half is the one
a draft would drop.** The answer leaves the gateway's machine, and the utterance
leaves the browsing device — and the component that transmits it off the browsing
device is **our front end**, which ADR-0168 §10 put in this repository, versioned
with it, shipped in the same distribution and served by the gateway. A boundary
defined as "the gateway's listener" would authorise the reply and leave the
request that provoked it prohibited, which is precisely the defect ADR-0124 §1
records architecture review finding in its own first draft.

**On loopback the front end transmitted too, and no clause was engaged**, because
the bytes never left the device. That is why this is the first moment the
front end has a boundary to be half of.

> **Normative.** `models/`, the `tools/` seam and the hub's remote transport are
> unchanged by this ADR. `models/` continues under ADR-0004 §2's permission as
> ADR-0017 §2 records it; the `tools/` seam stays designated under ADR-0154 and
> bounded by ADR-0155; and ADR-0124 §§2–8 govern the third boundary exactly as
> ratified. Nothing in this ADR discharges, weakens or substitutes for any
> condition of ADR-0017 §3, and **no lane may cite this ADR toward designating
> anything, toward registering an integration, or toward any clause of ADR-0155**.

**That is the whole of the widening.** It replaces ADR-0124 §1's enumeration and
nothing else, and §12 is the record.

**ADR-0017 §3's fourteen conditions do not bind this boundary, for the reason
ADR-0124 §1 gave and which holds here more plainly still.** §3's subject is
stated in its own heading — *conditions on designating the `tools/` seam* — and
its list is shaped by a destination chosen at call time from arguments a model
produced: canonicalisation per protocol, multi-recipient authorisation as one
set, name resolution as a gated call. None of those has a subject here. The
destination is not selected by anything; it is the browser that opened the
connection, and it is either admitted under §4 or refused.

**Why a fourth boundary costs ADR-0017 §4's property nothing, in its own terms.**
§4 found that the rationale is about egress being **accountable** — "few, named,
and answerable for what it sends" — "never about the number of accountable
places", and that "'One' was never argued for; it was a count of the subsystems
that existed." Three was a count as well.

- **Named.** Both halves are artifacts of this repository in one package —
  `src/ai_assistant/interfaces/gateway/` and the bundle it serves (ADR-0168 §10)
  — and no new package is created.
- **Few.** The recipients are the browsers on devices the owner **named at the
  gateway**, holding a session the gateway minted from a value disclosed once on
  its own standard output (§4). No model, plan, tool or hub response can add to
  that set, and no request on any listener can.
- **Answerable for what it sends.** The gateway sends the front end's own assets
  and the rendering of the calls the promoted engine surface answered for the
  request that browser just made (ADR-0168 §1's biconditional, unchanged), and
  the front end sends the request the owner typed. Both are bounded by ADR-0168
  §8's figures as §8 below applies them.

**And the recipient is the principal — with one difference from the third
boundary that is stated rather than absorbed.** A belief crossing this boundary
is disclosed to the owner, on a device of the owner's own overlay, under
ADR-0099 §1's single principal. What differs from ADR-0124 §1 is that the
recipient program is a **browser**: a general-purpose runtime this project did
not write, running our front end beside whatever else the owner has open, on a
device that may not be one the owner enrolled at the hub. ADR-0168 §6 already
states the residual that follows — "script running on the gateway's own origin
defeats both halves, because it need not read either" — and §5 below records
which of its bounds on that residual survive the move and which do not.

**Honest accounting.** This is the second listening boundary and the first whose
population is a *set of devices* rather than a set of processes on one machine.
§2 is what keeps that set off the public internet, §3 is what makes the caller's
device a fact the gateway obtains rather than accepts, and §4 is what keeps
membership in that set from being admission on its own.

### 2. The transport posture is ADR-0124 §2's, taken whole

> **Normative.** The gateway's remote browser listener is reachable only over an
> **overlay network** satisfying ADR-0124 §2's three properties, which this ADR
> adopts by reference and does not restate: every participant authenticated by
> the overlay before any byte of this protocol is exchanged; the payload
> encrypted end to end between the two participating devices, such that no third
> party — the overlay's operator and any relay it routes through included —
> holds a key that decrypts it; and membership administered by the owner.

> **Normative.** The remote browser listener binds only an address that exists on
> that overlay. It may not bind a wildcard address, an address of a physical
> interface, a loopback address, or any address reachable from the public
> internet, and a configuration that would have it do so is refused at load
> rather than bound.

> **Normative.** The remote browser listener is **off unless it is configured
> on**. A gateway with no remote-browser-listener configuration binds only
> ADR-0168 §2's loopback listener, and that loopback listener is bound whether or
> not this one is, under every clause of ADR-0168 §2 that this ADR does not
> supersede.

> **Normative.** Nothing in this ADR is conditioned on Tailscale. ADR-0124 §2's
> acceptance is of an overlay rather than of a vendor, and moving to another
> overlay satisfying that clause reopens no clause of this ADR.

> **Normative.** ADR-0124 §3's disclosure account is unchanged and is not
> re-accepted here: this ADR adds no participant to the overlay's control plane,
> transmits nothing to one, and does not import, embed, link in or launch the
> overlay agent. The gateway binds an address the agent provides and reads the
> agent over a local interface, exactly as ADR-0124 §4 has the hub do.

**Adopting §2 by reference rather than restating it is deliberate, and ADR-0172
§6 is the precedent.** Two documents stating the same obligation in slightly
different words is the drift ADR-0089 §2 records finding *in the section defining
the prevention*. ADR-0124 §2 is ratified and settled; pointing at it costs a
citation and cannot diverge from it.

> **Normative.** An operator-configured proxy, port forward, tunnel or overlay
> "serve" feature placed in front of the **loopback** listener is not this
> boundary and is authorised by no clause of this ADR. ADR-0168 §2's prohibition
> on it stands and is reinforced rather than lifted.

**That prohibition survives the fourth boundary, and it survives on a mechanical
ground rather than only a ledger one.** ADR-0168 §2 refused to bless a proxy
because "the data still left the device" and the boundary being "technically
unbroken in our socket options is not the boundary holding". A fourth boundary
answers that objection — the data may now leave — and a second one takes its
place: **a terminating proxy destroys the fact §3 requires.** A connection
arriving through one is a connection from the proxy, so the gateway's `whois` on
its peer address learns about the proxy and not about the browsing device, and
the only remaining source of the device's identity is a header the proxy asserts
— which ADR-0124 §4 forbids taking, in terms, and which ADR-0168 §3 forbids the
corpus being taught to take. So the arrangement that looks like a shortcut to
this boundary is the one arrangement that cannot satisfy it.

**The count in ADR-0168 §2's own sentence goes stale and its instruction does
not, which is why no supersession is owed on that clause.** It reads "it is
outside ADR-0124 §1's enumeration of the three authorised boundaries, and no
clause of this ADR authorises it": after §1 above the enumeration has four, and a
proxy path is outside it still. A reader holding only ADR-0168 §2 refuses a proxy
and is right to.

### 3. The gateway obtains the browsing device's overlay identity, and takes it from nothing the peer asserts

> **Normative.** Before serving anything on the remote browser listener — a
> static asset and the bootstrap exchange included — the gateway obtains the
> connecting device's overlay identity from the overlay agent running on the
> gateway's **own** machine, over a local interface. It may not take that
> identity from anything the peer asserts — a header, a cookie, a query
> parameter, a request body — and it may not obtain it by a call that leaves the
> machine. A connection whose overlay identity cannot be obtained is refused and
> closed.

> **Normative.** That check runs before ADR-0168 §7's `Host` and `Origin` checks
> and before any session is read, so a refusal on it discloses nothing about
> whether a session exists, and a connection refused on it reaches no clause of
> ADR-0168 §3, §4, §5 or §6 at all.

> **Normative.** The overlay identity a connection carries is a **Tier 2** fact
> about a device and is recorded on the gateway's admission decisions under
> ADR-0168 §6's record clause, in place of nothing — the loopback listener had no
> such fact to record. Its permitted appearance is an addition to ADR-0168 §6's
> enumeration for records written about a connection on this listener, and to no
> other record.

**This is ADR-0124 §4's obligation arriving at a door that can finally satisfy
it.** ADR-0084 §1 has the client read the peer's credentials from the kernel and
gives the reason — filesystem checks are "a walk over topology the operator
controls, and a walk can be wrong"; ADR-0124 §4 restates that "in terms of the
fact rather than the syscall" for a network, because `SO_PEERCRED` has no
analogue across one. The gateway's browser listener is the third door to face the
same question, and unlike the loopback one it has the same answer available: the
`whois` call `service/overlay.py` already makes, on the socket
`wire/overlay.py` already holds to custody conditions.

**Recording the identity is a genuine strengthening rather than a courtesy, and
it is worth naming because it is the one place this boundary is better off than
the one it extends.** ADR-0124 §7 has the hub record "each admission and each
refusal with the device it named". ADR-0168 §6 could record no such thing — its
enumeration of permitted Tier 2 facts is the instant, the request's class, the
outcome, the refusal condition and a count, and a loopback peer has no identity
worth naming. Here there is one, it is attested rather than asserted, and an
owner reading a refusal learns *which of their devices* was refused.

**Adding a field to ADR-0168 §6's enumeration supersedes it, and calling that an
"addition" was an error an earlier draft of this section made.** §6's enumeration
is **exclusive** — "No such record carries anything outside that enumeration" —
and it is exclusive because an earlier draft of *that* ADR used an exclusion list
which would have admitted the utterance out of a refused `ask`. A sentence saying
a record carries nothing outside a list does not survive the list gaining a
member: it becomes false, and a reader holding only §6 rejects a record this ADR
requires. Architecture review found the misclassification on its first round, and
§12 carries the record rather than the excuse.

**What the supersession is careful to keep is the enumeration's *form*, which is
the whole of why §6 is safe.** The record still names what may appear rather than
what may not, so a later lane adding a request shape nobody has thought of yet
inherits a closed list. The one new member is a Tier 2 fact about a *device*,
decidable before the request is parsed, and everything §6 excludes — session
halves, verifiers, bootstrap values, bodies, paths, query strings, headers,
cookies, and anything the hub or a model returned — stays excluded, on the remote
listener exactly as on the loopback one.

**The client-side half of ADR-0124 §4 has no analogue here, and saying so is
better than manufacturing one.** ADR-0124 §4 requires the *client* to confirm the
hub's overlay identity before sending anything, because a client is our code and
holds an enrolled hub identity beside its credential. The front end is our code
but the value it would compare against is one no browser can hold in the place
ADR-0004 §3 names, and the address it dials is the URL the owner typed. What
stands in that clause's place is the overlay itself: the transport authenticates
both participants before any byte is exchanged (§2), so the front end is speaking
to the device that holds that address or it is speaking to nothing. That is
weaker than ADR-0124 §4's client clause — it authenticates a *node*, not a
*value the owner enrolled* — and the residual is that an owner who types the
wrong overlay address reaches the wrong device of their own overlay and is told
nothing about it.

**What that residual reaches is the bootstrap value, and it is §4's device clause
rather than §6's `Host` rule that stops it becoming a session.** An earlier draft
of this section said the `Host` rule bounded it — "the wrong device does not serve
this listener, so the exchange fails" — and that is false about the attack that
matters. A `Host` rule is a rule *this* gateway applies to requests *it* receives;
it says nothing about what a **different** overlay member serves. A hostile member
occupying the address the owner mistyped serves its own look-alike page at its own
authority, the browser is satisfied, and the owner types the bootstrap value into
it. Adversarial review found it on the first round, and ADR-0124 §4 had already
ruled that this class of omission "is the whole of the attack" for the CLI rather
than a residual to accept.

**Two clauses stop the phished value short of a session, and they close the two
routes it can take.** Relayed from the hostile member's **own** device, the
exchange is refused because §4 admits it only from an overlay identity the owner
named at the gateway, and the attacker's is not one. Relayed through the owner's
**own** browser — a `fetch` the attacker's page issues to the real gateway — it is
refused by §6, because that request carries the attacker's `Origin` and not the
gateway's. What is left is a value an attacker holds and cannot spend, an
unexchanged value still live at the real gateway, and an owner who believes they
have used their assistant and has not. That is a phishing residual on a human
check — read the address the gateway printed — and it is stated rather than
claimed closed.

### 4. Admission is two facts, and only the assets are served on membership alone

> **Normative.** On the remote browser listener a request is admitted only when
> both hold: the overlay identity §3 obtained names a device the owner listed in
> `gateway_remote_browser_devices`, and the request carries a live web session
> under ADR-0168 §4 and §6. Neither fact admits a request on its own.

> **Normative.** ADR-0168 §3's two pre-session exceptions keep their extent and
> are separated on this listener, because they are not alike in what they hand
> back. The front end's own **static assets** are served to any device of the
> overlay the gateway's agent serves. The **bootstrap exchange** is served only to
> a device the owner listed, and a bootstrap exchange arriving from any other
> overlay identity is refused without the value being read, compared or consumed.
> Nothing else is served without a live session, and a request arriving without
> one is refused with a refusal carrying no assistant content, no fact about the
> hub's state and no fact about whether the hub is reachable, exactly as ADR-0168
> §3 requires.

> **Normative.** Listing a device is an act the owner performs **at the gateway**,
> in that gateway's configuration. No request on any listener may add to the list,
> extend it or modify it, and no model, plan, tool or hub response may.

> **Normative.** This ADR creates no enrolment, no grant and no principal, and
> **listing a device is none of the three**. A listed device is not enrolled under
> ADR-0124 §6 — nothing is minted, nothing durable is recorded and nothing is
> revoked — is not a device in ADR-0124 §5's sense of the unit of admission to the
> hub, is not an ADR-0097 grant, and carries no principal of its own (ADR-0099
> §1). No lane may present the list as an enrolment record, key any rule on it
> beyond §4's admission, or cite this ADR toward a device-scoped permission,
> capability or ceiling. The hub's admission stays
> exactly ADR-0124 §7's two facts about the **gateway's** device, and ADR-0168
> §3's prohibition on anything about a browser reaching the hub is untouched: no
> browser identity, session value or per-browser identifier crosses the wire in
> any frame.

> **Normative.** No rule may be conditioned on the gateway being able to tell two
> browsers on one device apart. The overlay identity §3 obtains names a device,
> and a device runs browsers.

**Membership alone is not admission, and ADR-0124 §2's argument for that is the
one that transfers.** That section refused to admit the hub's callers on overlay
membership alone because "networks acquire members: an ACL edit, a shared node, a
device the owner adds for an unrelated reason. Admitting on membership alone
would mean the hub admits on a decision the owner never made *at the hub*." The
same sentence holds one hop out with one word changed, and the decision the owner
makes *at the gateway* is now two acts rather than one: listing the device, and
disclosing the bootstrap value to it.

**So the two facts here are structurally ADR-0124 §7's, with a different second
fact, and the substitution is what §5 exists to check.** The hub's second fact is
a credential minted by an act at the hub and held in the OS keyring; the
gateway's is a session minted by an act at the gateway and held in a browser,
under the ADR-0004 §3, §6 and §7 exemptions ADR-0172 ruled for exactly this class
of value. This ADR does not reopen any of them.

**Splitting the two exceptions is a correction rather than a refinement, and the
draft it corrects is worth recording because its reasoning is the tempting one.**
That draft served both on membership alone, on the ground that ADR-0168 §3
guarantees neither "carries assistant content, a fact about the hub's state, or a
fact about whether the hub is reachable" — so both were treated as responses that
carry nothing. **That is true of the assets and false of the exchange.** ADR-0168
§5 has a successful exchange "return nothing but the two session values §6
requires", and a session is the whole of what admits a browser to the device's
authority. Reading the two as alike is what let a hostile overlay member phish a
bootstrap value from a mistyped address and spend it from its own device (§3), and
adversarial review found it on the first round. The exception's *extent* is
unchanged — still exactly two request classes, still nothing else — and what
changed is that the one which hands back a credential is admitted on a fact the
owner supplied rather than on one the network did.

**What a listed device is, and what it deliberately is not.** It is the smallest
form of ADR-0124 §6's insight and nothing more: enrolment there exists because
"admitting on membership alone would mean the hub admits on a decision the owner
never made at the hub", and a list of overlay identities is that decision made at
the gateway. It mints nothing, records nothing durable, and revokes nothing — a
device leaves the list by being removed from configuration, and any session it
already holds dies with the gateway process (ADR-0168 §4) rather than being
revoked. The clause above states in terms that this is not an enrolment, and no
lane may build one out of it.

**What the assets stay on membership alone for, since the split could have taken
them too.** They are the bundle this repository ships to anyone who installs it,
so an overlay member obtains from them nothing they could not obtain from the
distribution, plus the knowledge that a gateway is running — which is the
disclosure ADR-0168 §9 requires the gateway to make on purpose, "so that a browser
reaching a running gateway learns that the hub is down rather than that nothing is
there". Listing a device before it may fetch a stylesheet would be ceremony
consuming a decision nobody asked for, which is ADR-0126 §11's finding and
ADR-0172 §3's restatement of it. The line is drawn at the response that hands back
a credential, because that is where the two differ.

### 5. What carries over of ADR-0168 §6's argument, clause by clause

ADR-0168 §6 argued the shape of a web session from the properties of a **loopback
TCP port**, and its §8 argued the figures from the absence of a `0600` bit on
one. A reader inheriting those clauses on a listener that is not loopback needs
to know which arguments moved with them. This section runs them.

> **Normative.** Every clause of ADR-0168 §3, §4, §5, §6 and §9 binds the remote
> browser listener exactly as it binds the loopback one, **except the four §12
> records as superseded** — §2's two, §4's sole-admitter clause and §6's record
> enumeration — and except as §6, §7 and §8 below state otherwise. This ADR
> restates no clause it does not supersede and modifies none, and where a reader
> finds this ADR and ADR-0168 addressing the same subject on a clause this ADR
> does not name, **ADR-0168 governs**.

**The two-value session carries over, and the mechanism it defends against is
unchanged.** ADR-0168 §6 made a session two values "because a cookie is scoped to
a host and not to a port", so a cookie set by `http://127.0.0.1:8422` is
presented to `http://127.0.0.1:9000`. Cookie scope has no port component on any
host, so the same is true of `http://100.100.100.100:8422` and
`http://100.100.100.100:9000`, and the process that can exploit it is the same
one: a process on the **gateway's own machine** that can bind another port there
and draw the owner's browser to it. The remote listener neither introduces that
attacker nor removes it, so both halves are kept for the reason §6 gave, and the
distinct fault it requires for a header half that verifies against a cookie half
that does not is kept with them.

**The exfiltration asymmetry carries over whole.** §6 keeps a cookie half no
script can read because "an assistant's answer is **model output**, and a model
is not a trusted source of markup", so a value stolen out of origin-scoped
storage is not on its own a session. Nothing about that argument mentions
loopback.

**The disclosure argument for the bootstrap value carries over, and the one thing
that changes is stated.** §5's argument is about the **channel**: the value "sits
in the terminal where the owner started the gateway — a place they already have
the standing to read the process's own memory from", it is single-use, and 128
bits makes guessing it from the port unavailable. Every limb of that is
unchanged; the gateway still discloses on its own standard output and nowhere
else. What is new is that the owner must now **carry** the value from that
terminal to another device, and that the exchange then crosses a wire.

> **Normative.** A value of ADR-0172 §1's web-session credential class may cross
> the fourth boundary only under §2's transport posture. It is never placed in a
> URL, in a query string, in a log record or in any error, exactly as ADR-0168 §5
> and §6 already require, and its transit is the overlay's end-to-end encryption
> or it does not happen.

**That clause is a stacked addition on ADR-0172 rather than a change to it, and
ADR-0172's own Revisit clause is why.** That ADR anticipated this case by name —
"when a browsing device cannot host a gateway, which ADR-0168 §2 already sends to
a fourth-egress-boundary decision and which **would put a session credential on a
wire between two machines**" — so the deferring sentence stays true and now has
an answer, which is ADR-0083 §15's stacked addition on its own test. Every clause
of ADR-0172 stays true besides: §1's class is closed and gains no fourth member,
§2's replacement (b) is about what is at rest rather than what is in transit and
the values still never leave the gateway's process memory, (c)'s custody is still
the browser profile's file permissions, (d)'s bound is still the gateway
process's life, §4's removing act is still stopping the gateway, and §5's ruling
that a successful read is not recorded is untouched. §12 records the finding.

**What the overlay buys the transit is exactly what it buys the hub's
credential.** ADR-0124 §7 already carries a 128-bit device credential across this
same overlay in a connect frame, under §2's clause that no third party holds a
key. A bootstrap value and a session's two halves cross the same overlay under
the same clause. This ADR claims no more than that and no less.

**What does *not* carry over is the CSP's arithmetic, and it needs one word
changed rather than an argument.** ADR-0168 §6 requires a content security policy
permitting scripts, styles, fonts, images, media and connections "from its own
origin alone", and no inline script. The rule is unchanged; the origin it names
is now whichever authority §6 below admits the request on, and a policy naming a
loopback origin on a remote listener would forbid the page's own assets. The
text-not-markup clause is untouched in every word.

### 6. `Host` and `Origin` on a listener that is not loopback

> **Normative.** On the remote browser listener the gateway refuses any request
> whose `Host` header is not one of: the overlay address it bound, with the port
> it bound; or a name the owner configured in `gateway_remote_host_names`, with
> that port. The comparison is literal against the configured set. **The gateway
> resolves nothing**: it never asks a resolver what a name means, and a name in
> that set is admitted as a `Host` value and never used as a destination.

> **Normative.** `gateway_remote_host_names` is §8's field and §8 is the single
> statement of what it holds, what its default is and when it is refused. This
> section states only what the gateway does with it, and adds no condition on it.

> **Normative.** The gateway refuses any request carrying an `Origin` that is not
> the origin of the authority its own `Host` header named, and sends no
> cross-origin resource sharing header and honours no preflight, exactly as
> ADR-0168 §7 requires. Both checks run after §3's identity check and before any
> session is read.

**The `Host` check keeps the job ADR-0168 §7 gave it, and the job is still
live.** §7's reason is DNS rebinding: "a page the owner visits from a name the
attacker controls can have that name re-resolve to `127.0.0.1`" — and it
re-resolves to an overlay address just as easily, because rebinding is a property
of the attacker's own name rather than of the target. A literal allow-list of
authorities refuses the attacker's name one step before the session logic, which
is exactly what §7 bought.

**Admitting a configured name is a real widening and it is distinguished from
#912's posture rather than sliding past it.** #912 records that
`wire.address.check_remote_address` refuses a MagicDNS name for the hub's
*destination*, and ADR-0124 §1's ground for it: a client "obtains its destination
from configuration and never from a discovery mechanism", so a name in
configuration would make the destination "a fact about that resolver rather than
about the deployment". A `Host` header is not a destination. It is a string the
browser reports about the URL the owner typed, compared against a set the owner
configured, by a gateway that resolves nothing and binds an address its own agent
gave it. Both ends of #912's concern are absent: no resolver participates in what
this gateway does, and no name selects where anything is sent.

**The cost of refusing names outright was weighed against the cost of admitting
configured ones, and the phone is what decides it.** An owner typing an address
into a laptop's URL bar reads it out of `tailscale status` once; an owner typing
one into a phone does it on a soft keyboard, repeatedly, and will reach for the
MagicDNS name the overlay gave the machine. Refusing it would make the
milestone's own exit test hostile for no security gain — the attacker's name is
refused either way, because it is not in the set.

**What an owner reaching one gateway at two authorities gets is two sessions, and
it is a usability fact rather than a hole.** A cookie is scoped to a host and
browser storage to an origin, so a session minted at `100.100.100.100:8422` does
not admit at `laptop.example.ts.net:8422`; under ADR-0168 §5's one mint per
process, the second authority cannot get one at all until the gateway restarts.
The honest instruction is to pick one authority and stay on it, and §9 is where
the one-mint rule is left standing rather than relaxed.

### 7. The scheme is what the overlay gives, and the secure-context cost is named

> **Normative.** The remote browser listener speaks the same plain HTTP the
> loopback listener speaks. This ADR decides no transport-layer security
> arrangement for it, authorises no certificate, no key material and no
> certificate-provisioning act, and **no lane may read §2's end-to-end encryption
> as supplying a secure context in a browser**. The two are different properties
> and only the first is decided here.

> **Normative.** A browser-facing capability that is available only in a secure
> context is not authorised by this ADR. A lane that finds the milestone-14
> browser surface requires one — the Notification API, the Push API, a service
> worker, `crypto.subtle`, or microphone capture among them — **stops** and owes
> a ratified decision on the scheme, rather than working around the requirement,
> degrading it silently, or reaching for a certificate on its own authority.

**The confidentiality condition this boundary owes is met, and the browser
condition is a different one.** §2 requires the payload to be encrypted end to end
between the two devices with no third party holding a key, and the overlay
supplies exactly that for the browser leg as it does for the hub leg — the same
WireGuard tunnel ADR-0124 §2 accepted. So the boundary's own protection is not
what is missing. What is missing is that **the browser does not know it**: a page
served over `http://` from an address that is not loopback is not a
"potentially trustworthy origin", so the browser marks it insecure and withholds
the capabilities it gates on that classification. Loopback got the classification
for free and nobody had to notice.

**This is stated as a stop condition rather than a caveat because of what
milestone 14's exit test says.** *A conversation and a pushed notification, end to
end, on a phone.* A notification rendered in the open page, driven by the delivery
connection ADR-0131 §2 holds, needs no secure context and is what this decision
supports. An operating-system notification on a locked phone needs the Notification
or Push API and therefore a service worker, and needs a secure context for both.
Which of the two the exit test means is the milestone-14 surface lane's question
and the owner's ruling, not this ADR's — but a lane that discovers it *after*
building the surface has discovered it in the most expensive place, so the clause
above makes the discovery a stop.

**Three ways of buying a secure context were examined and none is taken here.**
An overlay-issued certificate for a MagicDNS name is the workable one, and it
costs an operating act with a control-plane feature behind it, a dependence on
names #912's posture is careful about, and a renewal story — a real decision,
with real conditions, that wants the surface lane's requirement in hand before it
is made. A self-signed certificate trains the owner to click through a warning,
which is a habit worth more than the capability. Terminating TLS in an overlay
"serve" feature is refused by §2 on the mechanical ground that it destroys the
peer identity §3 requires. §11 defers the question with the trigger above.

### 8. The gateway's ceilings are the gateway's, not each listener's

> **Normative.** Adding the remote browser listener may not let any figure
> ADR-0168 §8 names be exceeded. `gateway_max_browser_connections`,
> `gateway_max_pending_connections`, `gateway_max_sessions`,
> `gateway_max_hub_connections` and `gateway_record_interval` are the gateway's
> totals: a connection on either listener counts against the same figure, a
> session minted through either counts against the same ceiling, and the
> gateway's hub connections are counted once across both.

> **Normative.** `gateway_read_timeout` and `gateway_max_request_bytes` bind a
> connection and a request on either listener identically, and ADR-0168 §8's
> admitted-versus-unadmitted rule is read with §4 above: a connection on the
> remote listener is admitted from the moment it carries a request admitted under
> §4, and a connection refused under §3 is unadmitted and is closed.

**This clause refuses a reading rather than changing one, and ADR-0124 §7 is why
it has to exist at all.** ADR-0168 §8's figures are written over "the gateway" —
it "holds at most `gateway_max_browser_connections` connections of both kinds
together" — so the shared reading is the one its own words give and every
sentence of §8 stays true under it. But ADR-0124 §7 spent a clause on exactly this
because "a second listener is the natural place to double a budget by accident",
and its §11 step 11 is a validation step for the failure "an implementation fails
by giving each listener its own counter, which every other step here would still
pass". A decision that adds the second listener and says nothing invites the
mistake it can most cheaply prevent.

**The ceilings are owed here with the same force ADR-0168 §8 claimed and for a
partly different reason.** §8 argued them from the absence of a `0600` bit: the
loopback port "is reachable by every local process and every local user, which is
the whole reason a session exists at all". That population is unchanged — the
loopback listener is still bound — and a second one is added: every device on the
overlay. §2 bounds that second population to the owner's own devices, which is
smaller and authenticated, so the ceilings are not *more* urgent on this listener
than on the other; what matters is that they are one budget rather than two, and
that a peer saturating one door cannot leave the owner's other door looking like
a gateway that is down. That is ADR-0083's ruling 4 applied to a resource, which
is the ground `gateway_max_hub_connections` already stands on.

**The new `Settings` fields, and the one departure from ADR-0168 §8's own rule.**

| `Settings` field | Type | Default |
| --- | --- | --- |
| `gateway_remote_address` | `str \| None` | unset |
| `gateway_remote_browser_devices` | `tuple[str, ...]` | empty |
| `gateway_remote_host_names` | `tuple[str, ...]` | empty |

> **Normative.** `gateway_remote_address` is refused at settings load unless it
> is a literal address that is not a wildcard, not a loopback address, not a
> multicast address, not link-local and not reachable from the public internet —
> the five refusals `hub_remote_address` already carries, in the same shape and
> for the same reasons (ADR-0124 §2). Unset means the remote browser listener is
> off.

> **Normative.** `gateway_remote_browser_devices` holds the overlay identities
> §4 admits a bootstrap exchange from, in the stable form the overlay agent
> reports and this system already compares device identities in (ADR-0124 §4).
> Empty is the default and means **no device may exchange**, so a gateway
> configured on serves its assets and mints no remote session until the owner
> names a device.

> **Normative.** `gateway_remote_host_names` holds the additional authorities §6
> admits a `Host` header to name. Empty is the default, so a gateway configured on
> serves the address it bound and nothing else.

> **Normative.** Either list being non-empty while `gateway_remote_address` is
> unset is **refused at settings load**. Both are permissions the owner wrote
> about a listener, so a configuration that carries one while the listener is off
> is one no reading makes true, and neither is ignored silently.

> **Normative.** Every element of `gateway_remote_browser_devices` is held to the
> invariant this system already holds an overlay identity to — non-blank,
> encodable as UTF-8, and at most `MAX_OVERLAY_IDENTITY_BYTES` bytes encoded —
> and the check is **split across two places, because golden rule 2 puts the
> bound outside `core`**. `Settings` refuses at load what it can decide without
> importing anything: an element that is blank or has no UTF-8 form. The
> **gateway refuses at start**, before it binds or discloses a bootstrap value, an
> element over the byte bound, reading the constant the wire seam owns.

> **Normative.** No component of `core` may import that constant, and no lane may
> restate its value in `core` to move the check there. The bound has exactly one
> definition per package that owns one today, and this ADR adds no further copy.

> **Normative.** The list is read as a **set** of identities, compared for
> equality against the identity §3 obtained. A repeated element changes nothing
> and is not refused; order carries no meaning; and no element is matched by
> prefix, suffix, pattern or any form of partial comparison.

> **Normative.** No figure bounds the list's length, and none is owed. It is
> configuration the owner writes, it is not supplied by any peer, and §4 consults
> it on one request class that ADR-0168 §5 already limits to one exchange per
> gateway process — so there is no caller who can grow it and no path a large one
> could be spent on. A lane that measures a real cost may buy a figure then.

> **Normative.** The remote browser listener binds `gateway_port`, on the address
> above. No second port figure is added: the two listeners differ in address, so
> one port cannot collide with the other, and a second figure would buy an owner
> nothing they cannot get by changing the one.

> **Normative.** ADR-0168 §8's rule that "none of them is nullable, and none
> takes a value meaning 'off'" is stated over the ten fields in that ADR's own
> table and is untouched. `gateway_remote_address` is nullable *because it is the
> switch*, which is ADR-0124 §2's shape for the hub's own remote listener and the
> reason `hub_remote_address` is `str | None` in `core/config.py` today. A
> boundary that is off unless configured on needs a value meaning off.

> **Normative.** The gateway obtains the identity §3 requires from the overlay
> agent on its own machine, which is the fact `client_overlay_agent_socket`
> already names. That field's documented condition — ignored when
> `remote_hub_address` is unset — no longer holds, because a gateway may dial its
> hub over loopback and still serve browsers over the overlay; the condition
> widens to cover a set `gateway_remote_address`. No eleventh agent-socket field
> is owed, and the custody conditions `wire/overlay.py` enforces on that socket
> are applied unchanged.

**Naming the figures rather than leaving them is ADR-0168 §8's ground, taken from
ADR-0084 §3 and ADR-0083 §7: "a 'bounded default' with no figure is two
conforming stores handing the same continuation different history".** Three
fields are the whole of what this boundary adds and none of them is a budget:
one is the switch and two are lists the owner writes, because §8 above spends no
new budget — it shares the ones that exist.

**Refusing a stranded list rather than ignoring it is the one place these fields
depart from the corpus's usual companion-setting shape, and the reason is what
kind of value they are.** `hub_remote_port` and `client_overlay_agent_socket` are
documented as "ignored when" their switch is unset, and that is right for them: a
port number and a socket path are neutral facts, and a neutral fact going unread
costs the owner nothing. A list of devices that may exchange a credential, and a
list of authorities the door will answer to, are **permissions** — an owner who
wrote one and got silence has a configuration that says something the running
process does not do, which is ADR-0083's ruling 4 failure arriving through the
settings file. Adversarial review found the asymmetry on the second round: the
device list already refused this state and the name list did not, and making them
alike was the smaller of the two repairs available.

**Validating each identity before the door rather than at it is the same ruling
one level down, and it reuses a constant rather than restating a number.**
`ai_assistant.wire.overlay`'s `_stable_id` already refuses a blank identity, one
with no UTF-8 form and one over `MAX_OVERLAY_IDENTITY_BYTES` — "an identity that
cannot be encoded cannot be recorded, compared or reported" — and
`service/enrolment.py` and `service/admin.py` each apply the same bound where an
identity is *supplied* rather than obtained. A configured identity failing that
invariant is one the agent can never report, so without an up-front check the
owner's named device is refused at every exchange with nothing saying why: the
configuration would be silently unsatisfiable, which is the failure the clause
above exists to prevent, arriving through the element instead of the list.
Adversarial review found it on the third round.

**Splitting that check across `Settings` and the gateway is not a compromise; it
is what golden rule 2 requires, and the corpus already splits the neighbouring
one exactly here.** `MAX_OVERLAY_IDENTITY_BYTES` is defined in
`ai_assistant.wire.overlay` and in `ai_assistant.service.overlay`, and in neither
case in `core` — so a `Settings` validator enforcing it would be `core` importing
a subsystem, which golden rule 2 forbids and `lint-imports` fails on, while a
`Settings` validator restating `128` would be the second copy the clause above
refuses. Architecture review found that on its first round, and the resolution is
ADR-0124 §2's own shape: `core/config.py` refuses the parts of
`hub_remote_address` that `ipaddress` can decide, and `ai_assistant.service.remote`
refuses at bind what only the overlay agent knows. One check, two places, each
where the fact it needs already lives. A gateway that will not start on a
malformed identity is also ADR-0168 §5's established shape — "a gateway that
cannot disclose its bootstrap value does not start, and reports why".

**A length figure is declined in the same breath, and the reason is which
direction the value comes from.** ADR-0168 §8's figures bound what a *caller* can
make the gateway hold; this list is what the *owner* wrote, on one request class
ADR-0168 §5 caps at one exchange per process. Naming a figure for it would be an
eleventh number defending nothing, which is the move ADR-0168 §8 itself refused
when it declined "an eighth figure for a queue nothing yet needs".

### 9. One bootstrap value still, one session still — and this is not ADR-0168 §5's revisit

> **Normative.** ADR-0168 §5 is unchanged by this ADR. A gateway process still
> mints one bootstrap value, discloses it exactly once on its own standard
> output, and mints no further session after that value is exchanged until the
> process is restarted. This ADR does not relax that rule, does not authorise a
> second bootstrap value, and does not authorise a session that survives a
> gateway restart.

> **Normative.** ADR-0172 §2's replacement (d) is a **condition** of the ADR-0004
> §3, §6 and §7 exemptions rather than a description, and it is satisfied
> unchanged here: every value in that class still ceases to admit anything no
> later than the end of the gateway process. No lane may read this ADR as having
> removed that bound; a design that removes it loses the exemption and owes its
> own ratified decision, exactly as ADR-0172 §2 states.

**Milestone 14's exit test is reachable under §5 as it stands, and the arithmetic
is worth showing because it is close.** The test is a conversation and a pushed
notification on **a phone**. One gateway process mints one bootstrap value; the
owner reads it from the terminal where they started the gateway, exchanges it
from the phone, and the phone holds the one session. Nothing in the test needs a
second browser. What the owner *cannot* do without restarting the gateway is keep
a laptop browser and a phone browser admitted at once — and that is the cost
ADR-0168's Consequences already state ("every gateway restart logs every browser
out, and a second browser needs a restart"), arriving in a place where it is more
annoying rather than in a new form.

**Relaxing it here was available and is refused, on three grounds.** ADR-0168 §12
defers the durable session and the credential that would make several browsers
practical to **milestone 16** by name, with session persistence as its trigger.
#1320 reaches the same conclusion from the other end: `gateway_max_sessions` is
inert while §5 stands, and "on that reading the field is early rather than wrong,
and the honest fix is a sentence in the superseding ADR" that lifts §5. And
ADR-0172 §2 makes the process-lifetime bound a condition of three ADR-0004
exemptions, so lifting it is not a milestone-14 convenience — it is a decision
that reopens a privacy supersession, and it belongs in the ratified decision that
authorises the durable session.

> **Normative.** **#1320 and #1329 are not decided here** and are left open.
> `gateway_max_sessions` remains inert for the reason #1320 records, unchanged by
> this ADR. An unexchanged bootstrap value still has no time bound, and this ADR
> supplies none.

**#1329 is examined rather than passed over, because this decision touches its
subject without changing its answer.** That issue records that ADR-0168 gives an
unexchanged bootstrap value no clock, so two conforming gateways could differ.
Nothing here selects between them. What this decision does change is the physical
story: the value must now be carried from the terminal to another device by the
owner, so the interval between disclosure and exchange is plausibly minutes
rather than seconds. That is a reason the question is worth answering and not a
reason this ADR is the place — a figure would be an eleventh `Settings` field and
a change to ADR-0168 §8's table and to its Consequences' field count, which
#1329's own text identifies as a change to a ratified decision. The disclosure
channel is unchanged, the single-use property is unchanged, and the exchange now
crosses a wire §5 above holds to §2's encryption. #1329 stays open on its own
terms.

**So the answer to the question the brief for this lane asked is explicit: this
is not the §5 revisit.** Milestone 16 is, on ADR-0168 §12's own trigger, and both
issues hold together until then.

### 10. The gateway never dials a browser

> **Normative.** Whatever carries a message to a browser is established by the
> browser, and the gateway writes on it only in answer to something the browser
> asked for. An overlay address for a browsing device is not permission to
> initiate a connection to it, and no clause of this ADR authorises the gateway
> to open one.

> **Normative.** ADR-0094 §2 and ADR-0124 §10 are untouched and reinforced. The
> hub still never dials a spoke, and nothing here — including an overlay on which
> the gateway can address a browsing device — is permission to initiate one in
> either relationship.

**This clause exists because this is the second moment the forbidden thing
becomes easy, and the first one is on the record.** ADR-0124 §10 wrote the same
prohibition for the hub because an overlay "gives the hub a routable address for
every enrolled device, and the shortest path to a notification is to use it".
Milestone 14 *is* the notification milestone, the browsing device is now on an
overlay, and the shortest path to a phone notification is a connection the
gateway opens. ADR-0168 §12 already stated the direction rule this inherits —
"whatever carries a message to a browser is established by the browser" — as a
constraint on a surface it declined to design. Restating it here is what keeps a
fourth boundary from being read as the delivery channel it is a prerequisite for
and does not supply.

**What this ADR supplies to milestone 14's push consumer is a network path and
nothing else**, which is exactly the distinction ADR-0124 §10 drew: "the overlay
makes the *network* path bidirectional… What stands between that and a delivered
notification is not networking."

### 11. What this decides no part of

> **Normative.** This ADR decides no `core/protocols.py` and no `core/types.py`
> surface. A lane implementing it that finds it needs either stops and owes its
> own contract ADR, merged first (golden rule 5, ADR-0015 §5).

> **Normative.** It changes no member of the connect exchange, no frame's
> encoding and no method's arguments or results, so no lane implementing it
> changes `PROTOCOL_VERSION` for it (ADR-0124 §9).

> **Normative.** It decides nothing ADR-0168 §12 defers that is not named in this
> section, adds no clause to ADR-0168 or ADR-0172, and reopens no ruling of
> either.

**Deferred, by name, each with the condition that fires it:**

- **The browser-facing surface itself** — request shapes, paths, the document,
  the streaming carrier, and how a conversation and a notification are rendered.
  ADR-0168 §12 leaves it to the implementing lane and ADR-0173 §11 declines it
  again from the hub side, naming chunked transfer, an event stream and a socket
  the browser opened as alike-permitted; this ADR reaches none of it. What it
  adds is §10's direction rule restated for a remote browser and §7's stop
  condition on a secure context.
- **A transport-layer security arrangement for the remote browser listener**
  (§7). Fires when a browser capability the milestone-14 or milestone-15 surface
  requires is available only in a secure context, or when voice's first rung
  (#1318) asks for microphone capture in the browser, which is such a capability.
- **Fanning one delivery out to several browsers.** ADR-0131 §2 gives a device at
  most one delivery connection and ADR-0168 §12 records the fan-out as milestone
  14's, "the first consumer of that seam and the decision that will have a
  browser surface in hand". Nothing here decides it, and nothing here forecloses
  it. One thing it does change is the arrangement it happens in: a gateway may now
  run on the hub's own machine, where it reaches the hub over loopback rather
  than over the hub's remote listener.
- **Which of the promoted engine's operations a browser may reach.** ADR-0168
  §12 records that the five connection methods are refused on the hub's remote
  listener and refused client-side by the remote client, and hands that to
  milestone 15. **A gateway dialling its hub over loopback does not meet that
  refusal**, and no lane may read the deployment choice this ADR permits as
  having lifted milestone 15's inheritance or decided anything about it. The
  question is milestone 15's, on its own ratified decision.
- **A session that survives a gateway restart, a durable browser credential, and
  a second live session** (§9). ADR-0168 §5 and §12 defer them to milestone 16,
  ADR-0172 §2 makes the process-lifetime bound a condition of three exemptions,
  and #1320 and #1329 hold until that decision.
- **A device as a permission input, a context facet, or the audit trail's
  "approved from where"** (#920). A browsing device's overlay identity is now a
  fact the gateway holds, and §4 makes one admission turn on a list of them —
  which makes #920's questions more askable and answers no part of them. §4 states
  in terms that a listed device is not a principal, not a grant and not an
  enrolment, and forbids keying any rule on the list beyond that one admission;
  #920's three surfaces are each contract-shaped and owe their own ADRs. In
  particular the list is a **gateway-side door policy**, not a permission input:
  it decides who may exchange a bootstrap value, never what the assistant may do
  for them, and every browser it admits reaches exactly what the gateway's own
  device reaches and no more.
- **Whether the client may accept a name for the hub's destination** (#912).
  Untouched. §6 admits a configured name as a `Host` value only, and states why
  that is a different question.
- **Backup, restore and the delete act.** Unreached. ADR-0172 §4 already rules
  that stopping the gateway is the act that removes the web-session credential
  class and that no delete act is obliged to reach a gateway; this ADR changes
  neither half.

### 12. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

**Two clauses are superseded, in two ADRs, and both records land in this change.
No record is owed on any other ADR.**

- **ADR-0124 §1's rule as an enumeration — partially superseded (§1).** "User
  data may leave the device only from `models/`, from a designated integration
  seam inside `tools/`, or across the hub's **remote transport**… every other
  egress is a bug." §1 above adds a fourth boundary, so the sentence becomes
  false, and it becomes false twice over — the gateway's send and the front end's
  send are each an egress it forbids. A reader holding only ADR-0124 reads the
  browser hop as a bug and refuses to build it, which is what ADR-0168 §2 records
  that reader doing. **What survives is nearly all of ADR-0124.** §1's second
  clause constraining the client half of the *hub's* remote transport is
  untouched and still binds that client; §1's third clause leaving `models/` and
  the `tools/` seam unchanged is untouched and is restated in §1 above; §§2–8 are
  used as given, §2 by reference in §2 above and §4's obligation applied in §3
  above; §9's version rule is used as given and §11 above states that nothing
  here bumps; §10's prohibition on the hub dialling a spoke is untouched and
  reinforced by §10 above; §11's validation plan and §12's records are untouched.
  ADR-0124's `Status` already carries the leading `Partially superseded by`
  token, so this ADR's pair is **added** to that line without dropping the three
  already there (ADR-0070 §4), and the dated note is appended.
- **ADR-0168 §2's loopback-only bind clause and its one-gateway-one-device clause
  — partially superseded (§1, §2).** "The gateway's browser-facing listener binds
  a **loopback** address and only a loopback address… and no `Settings` value may
  make it do so", and "One gateway serves the browsers on its own device." A
  reader holding only ADR-0168 builds a gateway that cannot be configured to
  serve any browser but a local one, and after §2 above that is wrong of a
  separately configured remote browser listener. Both limbs fail ADR-0070 §1's
  first test rather than only its second: the reader acts differently, and the
  implementation in the tree — `_LOOPBACK` as a module constant, chosen so that
  "there is no configuration that could have it bind a wildcard, an interface or
  an overlay" — is that reader's work. **What survives, which matters more than
  what falls:** §2's clauses still bind the **loopback** listener in every word,
  and §2 above keeps that listener bound whether or not the remote one is; §2's
  proxy prohibition stands and is reinforced by §2 above on a second and
  mechanical ground; §2's third clause — that a gateway serving a browser on a
  device that cannot host one "is deferred, not decided" and "requires a fourth
  egress boundary" — **stays true and now has an answer**, which is ADR-0083
  §15's stacked addition on its own test rather than a supersession; and §1, §3,
  §4, §5, §6, §7, §9, §10, §11, §12 and §13 are untouched except where §3, §6 and
  §7 above state a rule *at the remote listener*, each of which is recorded in
  this list. ADR-0168's `Status` is plain `Accepted`, so it takes the leading
  `Partially superseded by` token and drops `Accepted` (ADR-0070 §4), with the
  dated note appended; it carries no amendment qualifier to move (ADR-0082 §2).

**No record is owed on the following, and each is examined rather than assumed.**

- **ADR-0017 §1 and §2.** Already replaced by ADR-0124 §1, which is what §1 above
  reads and replaces in turn. ADR-0070 §4's transitive rule governs — "a consumer
  that defers a scope to ADR-B follows ADR-B's own status onward" — so a reader
  arriving at ADR-0017 is already sent to ADR-0124 and from there to this ADR, and
  writing a fourth pair onto ADR-0017's line would record the same replacement
  twice. **§3's fourteen conditions stand entirely** and still govern designating
  the `tools/` seam and nothing else; §1 above states that no lane may cite this
  ADR toward them. §4's argument survives and is what licenses this widening, in
  its own words.
- **ADR-0168 §4's sole-admitter clause — partially superseded (§4), on the same
  scope.** "A **web session** … is the only thing that admits a browser request."
  §4 above makes admission on the remote listener turn on **two** facts, so a
  reader holding only §4 builds a door that admits a browser the gateway's own
  agent cannot place, and admits a bootstrap exchange from a device the owner
  never named. That is ADR-0070 §1's first limb. An earlier draft called this an
  addition rather than a replacement, on the reading that "the only thing that
  admits" is a claim about **sufficiency** and a second *necessary* fact leaves it
  true. The reading is defensible and it is not the test: ADR-0070 §1 asks whether
  the reader acts differently, and this one does. Architecture review found it.
  **What survives is the rest of §4 entire** — what a session is, its entropy and
  constant-time comparison, the verifier-only retention, the process-memory table,
  death with the process, continuous expiry, and refusing rather than evicting at
  the ceiling all bind the remote listener unchanged (§5 above), and §9 above
  declines to touch the ceiling's inertness.
- **ADR-0168 §6's exclusive record enumeration — partially superseded (§3), on
  the same scope.** "No such record carries anything outside that enumeration."
  §3 above requires the attested overlay identity on records about a connection on
  the remote listener, so the sentence becomes false there and a reader holding
  only §6 rejects a record this ADR requires. **What survives is the whole of §6
  besides**: the enumeration's exclusive *form*, every value it excludes, the
  trigger clause naming which decisions are recorded, the rate bound and its
  collapse key, the retention-free emission, the two-value session, the distinct
  replaced-cookie fault, the text-not-markup clause and the content-security
  policy — the last applied with the origin §6 above admits rather than a loopback
  one, which is the clause working rather than changing.
- **ADR-0168 §3, §5 and §9 — used as given, and §5 above makes them binding on
  the remote listener unchanged.** §3's two pre-session exceptions are unchanged
  in extent — still exactly those two request classes and nothing else — and gain
  prior conditions in §4 above, different ones for each: the assets on an attested
  overlay membership, the bootstrap exchange on a device the owner listed. Both
  **narrow** §3's population and neither widens it, so a reader holding only §3
  still serves no third thing without a session and is not wrong about anything
  §3 says. §5 is untouched and §9 above declines to relax it. §9 of that ADR binds
  the new listener word for word.
- **ADR-0168 §7 — used as given, and no record is owed.** Its `Host` and `Origin`
  checks are restated for a listener whose bound authority is not loopback (§6
  above); the check, its ordering and its reason are §7's. A record is not owed
  because §7's own text scopes the rule to "the loopback names it **bound**" — on
  a listener that bound others, a reader following §7 compares against what *it*
  bound, and acts identically before and after.
- **ADR-0172 — examined at length, and no record is owed.** Its Revisit clause
  names this decision by name and therefore **fires**; examining a revisit
  condition is not itself an amendment (the ADR-0083 §15 pattern, which ADR-0124
  §1 applied to ADR-0017 §3), and what matters is whether any clause becomes
  false. None does: §1's class is closed and gains no member here; §2's
  replacements (a)–(d) are each satisfied unchanged, (b) speaking to what is at
  rest rather than what is in transit and (d) held as a condition by §9 above;
  §3's gating exemption covers the same admission-path reads, to which §3 above
  adds a check that is not a Tier 0 read; §4's removing act is still stopping the
  gateway; §5's ruling that a successful read is not recorded is untouched by §3
  above, which records refusals and mints and adds no per-request record; §6's
  conditionality on ADR-0168 §4 and §6 is preserved by §5 above. §5 above's
  clause on the transit is a **stacked addition** under ADR-0082 §1 — the
  deferring sentence stays true and now has an answer — recorded here and
  nowhere else.
- **ADR-0004.** §1's tiers are used as given, and §3 above classifies an overlay
  identity as Tier 2 under them rather than around them. §2's residency clause is
  untouched: the assistant's own store does not move, and ADR-0155 §1 rules that
  the clause governs "the persistent data this system keeps on the owner's
  behalf, under the data directory `Settings.data_dir` resolves", decided "by
  where this system persists it". Nothing here persists anything anywhere new.
  §2's telemetry clause is unengaged for ADR-0124 §3's reason. §3, §6 and §7 are
  reached only through ADR-0172's exemptions, which §9 above leaves exactly as
  they are; §5's "logs are Tier 2 only" is what makes §3 above's added record
  field admissible, and is applied rather than narrowed.
- **ADR-0155 — examined, and not engaged.** §3's two prohibitions are written
  over "a span of an egress call **at the designated `tools/` egress seam**", and
  this boundary is not that seam; §1's third clause is about persistence a
  connected service performs, and a browser on the owner's own device is not a
  service another party operates. The content crossing this boundary *is* covered
  content in §3's sense — it derives from stores under `Settings.data_dir` — and
  that is exactly why the finding is stated rather than skipped: §3's subject is
  the seam, not the class, so no clause of ADR-0155 reaches a transmission to the
  owner's own browser. §1 above forbids citing this ADR toward any clause of it.
- **ADR-0154.** Untouched. Its designation, its fourteen attestations and its §6
  gate on registration are unreached, and §1 above forbids citing this ADR toward
  any of them.
- **ADR-0084 §1 and §11.** §1's sentence that a remote leg "owes its own ratified
  egress decision, and it cannot be reached by swapping an address family" is the
  sentence this ADR obeys rather than falsifies: this decision is not a change of
  address family, it is a boundary with its own admission rule. §1's finding that
  "a loopback listener moves bytes between two processes on one machine; it
  engages neither clause" is used as given in §3 above for the agent call. §11's
  deferrals are untouched. §3's frame ceiling, deadline and connection ceilings
  govern the wire between the gateway and the hub and are unreached; §6's
  own-console-script rule was already examined by ADR-0168 §1 and is not
  re-examined.
- **ADR-0094.** §1's vocabulary is used as given: the gateway is one spoke of the
  client profile, and serving a remote browser makes it no second kind of thing.
  §2's direction rule is restated and reinforced by §10 above. §5's band ceiling
  is neither set nor raised. §9's edge-state permission is unreached — this ADR
  adds no state the gateway holds; §8 above spends no new budget and §3 above
  records rather than retains. §10's second-spoke trigger is examined and does
  not fire, on ADR-0168 §13's reasoning: a gateway serving a browser on another
  device is the same profile exercising the same capability, and a second spoke
  that differs in nothing supplies no standing.
- **ADR-0131.** Used as given and nothing it decides is reopened. §2's one
  delivery connection per device and §4's identity rule are untouched; §11 above
  records the fan-out as milestone 14's and names the one arrangement fact this
  decision changes.
- **ADR-0173 — examined, and no record is owed.** Its subject is the hub-side
  half of streaming, and §11 of it states its own reach at this edge: it "does
  not decide the browser-facing carrier and does not reopen ADR-0168 §12's
  deferral of it", and it carries the same direction rule §10 above carries —
  "whatever carries a stream to a browser is established **by the browser**".
  Every sentence stays true after a fourth boundary: a stream still crosses the
  gateway↔hub leg ADR-0124 §1 authorises, the browser-facing carrier is still
  undecided by both texts, and §11 of that ADR already counts a streaming call
  against `gateway_max_hub_connections`, which §8 above makes a total across both
  listeners rather than a per-listener figure. Its clause that it "moves no
  egress boundary" is a statement about ADR-0173 and stays true; this ADR moves
  one, and does so at a different hop.
- **ADR-0097 and ADR-0099 §1.** Untouched. §4 above restates ADR-0124 §5's
  refusals for a browsing device, which is a new noun inviting the same mistake:
  no grant is created, no principal is added, and neither ADR is read more
  widely.
- **ADR-0125 and ADR-0126.** Used as given and neither exemption is cited,
  widened or rested on. The device credential the gateway reads to reach its hub
  stays in the OS keyring, read through the Protocol ADR-0125 §8 hands the
  client, under ADR-0124 §6's own exemption and no part of anything here
  (ADR-0172 §1 puts it outside the web-session class in terms).
- **ADR-0083.** Used as given. The hub's exclusivity is untouched, the gateway
  opens no store, and §8's package rule is obeyed — both halves of this boundary
  live in `interfaces/`, where ADR-0168 §1 put the gateway on golden rule 3's own
  terms.
- **Golden rules 1, 2 and 3.** Applied, not amended. The gateway still reaches
  the hub only through the promoted `AssistantEngine` Protocol, `core` gains
  nothing but `Settings` fields, and ADR-0168 §1's clauses making the adapter's
  thinness checkable bind the remote listener exactly as they bind the loopback
  one.

## Consequences

- **A fourth egress boundary exists**, and it is the first whose recipient is a
  program this project did not write. Its halves are the gateway's remote browser
  listener and the front-end bundle this repository ships; its path is an overlay
  the owner administers, encrypted end to end; and its recipient set is the
  browsers on that overlay holding a session the gateway minted (§1).
- **ADR-0124 §1's enumeration is superseded** and its §§2–10 are not. The next
  lane wanting to move data off a device inherits four boundaries and the same
  fourteen `tools/` conditions it inherited yesterday.
- **ADR-0168's gateway becomes configurable in the one way it was built not to
  be**, and only in that way: a second listener, off by default, on an overlay
  address the settings validator refuses to let be anything else. The loopback
  listener and every clause governing it are unchanged (§2).
- **Four clauses of ADR-0168 are partially superseded, each scoped to that second
  listener** (§12): §2's two, §4's sole-admitter clause and §6's exclusive record
  enumeration. A reader of ADR-0168 building the loopback gateway is right about
  every one of them; a reader building the remote one has a second document to
  read, which is the cost of a boundary the first ADR deferred rather than
  designed.
- **The corpus gains a fourth admission rule, and one principle still covers all
  four.** Loopback at the hub refuses a credential, the hub's remote listener
  requires one, the gateway's loopback listener requires a session, and the
  gateway's remote listener requires an attested device identity **and** a
  session — because admission never asserts a check that did not happen, and each
  door's answer is decided by what its transport already guarantees.
- **A browsing device becomes a fact the gateway holds**, attested by its own
  overlay agent, recorded on its admission decisions, and — for the one response
  that hands back a credential — checked against a list the owner wrote. That is
  a strict improvement on the loopback listener, which had no such fact, and it
  makes #920's questions more askable while answering none of them (§4, §11).
- **The owner acquires one configuration act they did not have**: naming the
  devices whose browsers may exchange a bootstrap value. It is deliberately the
  smallest form of ADR-0124 §6's insight — no mint, no durable record, no
  revocation act — and §4 forbids reading it as an enrolment, a grant or a
  permission input.
- **Milestone 14's exit test is reachable, and one thing about it is not settled
  by this decision.** A conversation and an in-page pushed notification on a
  phone need no secure context and are supported. An operating-system notification
  does, and §7 makes discovering that a **stop** on the surface lane rather than a
  workaround.
- **What becomes harder, first:** the page a phone loads is marked insecure by the
  browser, because plain HTTP on a non-loopback address is not a potentially
  trustworthy origin — even though §2's overlay encrypts it end to end. The
  browser cannot see the tunnel, and this decision does not teach it to (§7).
- **What becomes harder, second:** one bootstrap value per gateway process is a
  sharper cost when the browser is in another room. The owner reads it off the
  gateway's terminal and carries it, and a laptop browser and a phone browser
  cannot both be admitted without a restart. That is ADR-0168 §5 unchanged, and
  milestone 16 is where it is revisited (§9).
- **What becomes harder, third:** two authorities mean two sessions. A gateway
  reached at both its overlay address and a configured name has two cookie scopes
  and two storages, and under one mint per process only one of them can hold the
  session (§6).
- **#1320 and #1329 stay open**, and this decision is explicitly not the revisit
  either of them is waiting for (§9).
- **Revisit when** a browser capability the surface needs is available only in a
  secure context, which is §7's stop condition and the first thing that would
  reopen the scheme; when milestone 16 asks for session persistence, which
  reopens ADR-0168 §5 and ADR-0172 §2's condition together and makes both open
  issues due; when milestone 15 asks whether a browser may reach the connection
  methods, which a gateway dialling over loopback makes reachable and which §11
  refuses to decide; or when the chosen overlay stops satisfying ADR-0124 §2.

## Alternatives considered

- **Do nothing, and meet milestone 14's exit test with the gateway on the
  phone.** The arrangement ADR-0168 §2 chose, and the reason it was cheap there.
  *Not available.* A phone runs no Python process, so there is no placement that
  keeps the browser hop inside one device; that is the exact condition ADR-0168
  §2 named as firing this decision.
- **Read the browser leg into ADR-0124 §1's third boundary**, so no supersession
  is owed. *Rejected in Context.* The third boundary's accountability hangs off
  the hub's enrolment, its two-fact rule and its revocation record, none of which
  has a subject inside a browser — so the fold would import an admission rule
  with nothing to admit and leave the actual control outside the boundary meant
  to account for it.
- **Reach a gateway on the hub's machine through an overlay "serve" feature, an
  SSH tunnel or a reverse proxy.** Needs no code and appears to keep the listener
  on loopback. *Rejected in §2*, and now on two grounds rather than one: ADR-0168
  §2's ledger objection stands, and a terminating proxy additionally destroys the
  peer identity §3 requires, leaving a header the proxy asserts as the only
  source — which ADR-0124 §4 forbids taking in terms.
- **Put the browser-facing listener in the hub.** *Rejected*, on ADR-0168's own
  grounds, which this decision does not weaken: a large untrusted-input-facing
  HTTP surface inside the process holding five databases and the instance lock is
  the opposite of what ADR-0083's exclusivity is for, and `service` growing an
  interface adapter is what golden rule 3 and ADR-0083 §8 have no room for.
- **Admit a browser on overlay membership alone, with no session.** Genuinely
  arguable: the overlay authenticates every participant, so a device is already
  known. *Rejected in §4* on ADR-0124 §2's own reasoning — networks acquire
  members by ACL edits and shared nodes, so membership alone would admit on a
  decision the owner never made at the gateway. It would also re-export the
  device credential's whole authority to every device on the overlay, which is
  ADR-0168 §3's amplifier argument with a larger amplifier.
- **Serve the bootstrap exchange on overlay membership alone**, on the ground
  that ADR-0168 §3 guarantees its two pre-session exceptions carry nothing. The
  position an earlier draft took. *Rejected in §4 after adversarial review.* It is
  true of the assets and false of the exchange, which ADR-0168 §5 has return "the
  two session values §6 requires" — so a hostile overlay member at a mistyped
  address could phish a bootstrap value and spend it from its own device. §4 now
  admits the exchange only from a device the owner listed, which is the smallest
  form of the insight ADR-0124 §6 built enrolment out of.
- **Enrol the browsing device at the gateway**, minting a credential and holding a
  durable record, so the parallel with ADR-0124 §6 is complete. *Rejected in §4*,
  and it is the opposite error from the one above: a mint is a second Tier 0
  secret this milestone declined (ADR-0168 §5), a durable record is edge state
  ADR-0094 §9 permits only bounded and continuously destroyed, and a revocation
  act is machinery for a list the owner edits in a file. Naming an identity buys
  the whole of what §4 needs and none of that.
- **Require the gateway to read the hub's enrolment record before admitting a
  browsing device**, so the two-fact rule is the hub's own. *Not available, and
  self-defeating besides.* It needs a wire surface that does not exist, ADR-0124
  §6 forbids a remote connection reaching enrolment at all, and ADR-0168 §9
  requires the gateway to serve whether or not the hub is reachable — so a
  hub-gated browser admission could never deliver the message that the hub is
  down, which is the same failure ADR-0172 §3 identified for a hub-gated session
  read.
- **Terminate TLS on the remote browser listener**, so the page is a secure
  context and the browser stops marking it insecure. *Deferred in §7, not
  refused.* An overlay-issued certificate is the workable form and it costs an
  operating act with a control-plane feature behind it, a dependence on names
  #912's posture is careful about, and a renewal story — a real decision that
  wants the surface lane's requirement in hand. A self-signed certificate is
  refused outright: it trains the owner to click through a warning, and that
  habit is worth more than the capability.
- **Relax ADR-0168 §5's one mint per process**, so a laptop and a phone can both
  be admitted. *Rejected in §9.* ADR-0168 §12 defers it to milestone 16 by name,
  #1320 reaches the same conclusion from the ceiling's side, and ADR-0172 §2
  makes the process-lifetime bound a **condition** of three ADR-0004 exemptions
  — so lifting it is not a convenience but a decision reopening a privacy
  supersession.
- **Give the bootstrap value a time bound here**, since the owner now carries it
  between devices. *Rejected in §9.* It is an eleventh `Settings` field and a
  change to ADR-0168 §8's table and Consequences, which #1329's own text
  identifies as a change to a ratified decision, and the physical story this
  decision changes is a reason the question deserves answering rather than a
  reason this is the document.
- **A second port figure for the remote listener.** *Rejected in §8.* The two
  listeners differ in address so one port cannot collide with the other, and a
  figure buys an owner nothing they cannot get by changing the one that exists.
- **Refuse a configured `Host` name, admitting only the bound literal address**,
  keeping #912's posture uniform. *Rejected in §6.* A `Host` header is not a
  destination, the gateway resolves nothing either way, and refusing names would
  make the milestone's own exit test hostile on a phone for no security gain —
  the attacker's rebound name is refused either way, because it is not in the
  owner's set.
- **Give each listener its own ceilings**, since their populations differ.
  *Rejected in §8* on ADR-0124 §7's ground: a second listener is the natural place
  to double a budget by accident, and two listeners each honouring a figure
  independently means the gateway honours neither.
